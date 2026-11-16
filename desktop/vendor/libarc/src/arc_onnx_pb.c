/* Minimal protobuf for ONNX models (arc_onnx_pb.h), moved out of arc_nft2_ort.c unchanged.
 * Part of arc_transcriber (Whissle Inc.), CC BY-NC 4.0; see LICENSE. */
#include "arc_onnx_pb.h"

#include <stdlib.h>
#include <string.h>

#include "arc_base.h"

static int pb_varint(const uint8_t* p, size_t n, size_t* i, uint64_t* v) {
  uint64_t r = 0;
  for (int s = 0; s < 64; s += 7) {
    if (*i >= n) return -1;
    uint8_t c = p[(*i)++];
    r |= (uint64_t)(c & 127) << s;
    if (c < 128) {
      *v = r;
      return 0;
    }
  }
  return -1;
}
/* skip a field's payload; *len / *off of a length-delimited one */
static int pb_skip(const uint8_t* p, size_t n, size_t* i, int wt, size_t* off, size_t* len) {
  uint64_t v;
  switch (wt) {
    case 0: return pb_varint(p, n, i, &v);
    case 1: *i += 8; return *i <= n ? 0 : -1;
    case 5: *i += 4; return *i <= n ? 0 : -1;
    case 2:
      if (pb_varint(p, n, i, &v) || *i + v > n) return -1;
      if (off) *off = *i;
      if (len) *len = (size_t)v;
      *i += (size_t)v;
      return 0;
    default: return -1;
  }
}
static size_t pb_put_varint(uint8_t* o, uint64_t v) {
  size_t k = 0;
  do {
    uint8_t c = v & 127;
    v >>= 7;
    o[k++] = (uint8_t)(c | (v ? 128 : 0));
  } while (v);
  return k;
}

/* a TensorProto's name, type, dims and external data location (encoder.weights only) */
static int parse_tensor(const uint8_t* p, size_t n, arc_onnx_ext* t, int* is_ext) {
  size_t i = 0;
  memset(t, 0, sizeof *t);
  *is_ext = 0;
  int loc_ok = 0;
  while (i < n) {
    uint64_t key;
    if (pb_varint(p, n, &i, &key)) return -1;
    int f = (int)(key >> 3), wt = (int)(key & 7);
    size_t off = 0, len = 0;
    if (f == 1 && wt == 0) {   /* dims, unpacked */
      uint64_t v;
      if (pb_varint(p, n, &i, &v)) return -1;
      if (t->ndim < 8) t->dims[t->ndim++] = (int64_t)v;
    } else if (f == 1 && wt == 2) {   /* dims, packed */
      if (pb_skip(p, n, &i, 2, &off, &len)) return -1;
      size_t j = off;
      while (j < off + len) {
        uint64_t v;
        if (pb_varint(p, off + len, &j, &v)) return -1;
        if (t->ndim < 8) t->dims[t->ndim++] = (int64_t)v;
      }
    } else if (f == 2 && wt == 0) {
      uint64_t v;
      if (pb_varint(p, n, &i, &v)) return -1;
      t->dtype = (int)v;
    } else if (f == 8 && wt == 2) {
      if (pb_skip(p, n, &i, 2, &off, &len)) return -1;
      free(t->name);
      t->name = malloc(len + 1);
      if (!t->name) return -1;
      memcpy(t->name, p + off, len);
      t->name[len] = 0;
    } else if (f == 13 && wt == 2) {   /* external_data: StringStringEntryProto {1: key, 2: value} */
      if (pb_skip(p, n, &i, 2, &off, &len)) return -1;
      size_t j = off;
      char k[32] = {0}, v[256] = {0};
      while (j < off + len) {
        uint64_t key2;
        size_t o2 = 0, l2 = 0;
        if (pb_varint(p, off + len, &j, &key2)) return -1;
        if (pb_skip(p, off + len, &j, (int)(key2 & 7), &o2, &l2)) return -1;
        if ((key2 & 7) != 2) continue;
        char* dst = (key2 >> 3) == 1 ? k : (key2 >> 3) == 2 ? v : NULL;
        size_t cap = (key2 >> 3) == 1 ? sizeof k : sizeof v;
        if (dst && l2 < cap) {
          memcpy(dst, p + o2, l2);
          dst[l2] = 0;
        }
      }
      if (!strcmp(k, "location")) loc_ok = !strcmp(v, "encoder.weights");
      else if (!strcmp(k, "offset")) t->offset = strtoull(v, NULL, 10);
      else if (!strcmp(k, "length")) t->length = strtoull(v, NULL, 10);
    } else if (f == 14 && wt == 0) {
      uint64_t v;
      if (pb_varint(p, n, &i, &v)) return -1;
      *is_ext = v == 1;
    } else if (pb_skip(p, n, &i, wt, NULL, NULL))
      return -1;
  }
  if (*is_ext && !loc_ok) *is_ext = 0;   /* external data elsewhere: left to ONNX Runtime */
  return 0;
}

/* model bytes -> the same model with `extra_out` appended to the graph outputs (NULL: unchanged) and the list of the
 * graph's initializers stored in encoder.weights */
int arc_onnx_edit_model(const uint8_t* p, size_t n, const char* extra_out, uint8_t** out, size_t* out_n, arc_onnx_ext** ext,
                      int* n_ext) {
  size_t i = 0, g_tag = 0, g_off = 0, g_len = 0;
  int found = 0;
  while (i < n) {
    size_t at = i;
    uint64_t key;
    if (pb_varint(p, n, &i, &key)) return -1;
    size_t off = 0, len = 0;
    if (pb_skip(p, n, &i, (int)(key & 7), &off, &len)) return -1;
    if ((key >> 3) == 7 && (key & 7) == 2) {
      g_tag = at;
      g_off = off;
      g_len = len;
      found = 1;
    }
  }
  if (!found) {
    arc_seterr("nft2 onnx: no graph in the model");
    return -1;
  }
  /* the graph's initializers */
  int cap = 64;
  *ext = calloc((size_t)cap, sizeof(arc_onnx_ext));
  *n_ext = 0;
  const uint8_t* g = p + g_off;
  size_t j = 0;
  while (j < g_len) {
    uint64_t key;
    if (pb_varint(g, g_len, &j, &key)) return -1;
    size_t off = 0, len = 0;
    if (pb_skip(g, g_len, &j, (int)(key & 7), &off, &len)) return -1;
    if ((key >> 3) != 5 || (key & 7) != 2) continue;
    arc_onnx_ext t;
    int is_ext;
    if (parse_tensor(g + off, len, &t, &is_ext)) return -1;
    if (!is_ext) {
      free(t.name);
      continue;
    }
    if (*n_ext == cap) {
      cap *= 2;
      arc_onnx_ext* ne = realloc(*ext, sizeof(arc_onnx_ext) * (size_t)cap);
      if (!ne) return -1;
      *ext = ne;
    }
    (*ext)[(*n_ext)++] = t;
  }
  /* GraphProto.output (12) += ValueInfoProto {name, type {tensor_type {elem_type FLOAT}}} */
  uint8_t vi[600], extra[620];
  size_t nl = extra_out ? strlen(extra_out) : 0, vl = 0, el = 0;
  if (extra_out) {
    if (nl > 500) return -1;
    vi[vl++] = 0x0A;
    vl += pb_put_varint(vi + vl, nl);
    memcpy(vi + vl, extra_out, nl);
    vl += nl;
    const uint8_t ty[] = {0x12, 0x04, 0x0A, 0x02, 0x08, 0x01};
    memcpy(vi + vl, ty, sizeof ty);
    vl += sizeof ty;
    extra[el++] = 0x62;
    el += pb_put_varint(extra + el, vl);
    memcpy(extra + el, vi, vl);
    el += vl;
  }
  uint8_t lenb[16];
  size_t lb = pb_put_varint(lenb, g_len + el);
  size_t tag_len = 1;   /* field 7, wire type 2: 0x3A */
  *out_n = g_tag + tag_len + lb + g_len + el + (n - (g_off + g_len));
  *out = malloc(*out_n);
  if (!*out) return -1;
  uint8_t* o = *out;
  memcpy(o, p, g_tag);
  o += g_tag;
  *o++ = 0x3A;
  memcpy(o, lenb, lb);
  o += lb;
  memcpy(o, g, g_len);
  o += g_len;
  memcpy(o, extra, el);
  o += el;
  memcpy(o, p + g_off + g_len, n - (g_off + g_len));
  return 0;
}

