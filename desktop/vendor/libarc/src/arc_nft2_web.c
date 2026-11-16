/* NFT2 nets in the browser (issue #93 WebAssembly spike; CMake -DARC_NFT2_BACKEND=web under Emscripten): the same
 * five graphs as arc_nft2_ort.c, run by onnxruntime-web (its public JavaScript API, InferenceSession) instead of the
 * ONNX Runtime C API, which onnxruntime-web's npm WebAssembly does not expose (docs/EMBEDDING.md).
 *
 * The page sets, before the first arc_nft2_create:
 *   Module.ort             the onnxruntime-web module (import * as ort from ".../ort.wasm.min.mjs")
 *   Module.encoderWeights  encoder_onnx/encoder.weights as a Uint8Array (282 MB; NOT copied into libarc's heap)
 * and puts the rest of the nft2/ folder in the Emscripten file system. The encoder graphs are edited here in C (the
 * Arc tap appended as a graph output, arc_onnx_pb.c, exactly as the native backend does) and handed to JavaScript as
 * bytes; onnxruntime-web resolves their external data ("encoder.weights") from Module.encoderWeights.
 *
 * InferenceSession.run is asynchronous, so these calls suspend the C stack (EM_ASYNC_JS): link with -sASYNCIFY (or
 * -sJSPI). libarc's other C is unchanged and single-threaded here (no pthreads: its pool runs serially).
 * Part of arc_transcriber (Whissle Inc.), CC BY-NC 4.0; see LICENSE. */
#include "arc_nft2_be.h"

#include <emscripten.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "arc_onnx_pb.h"

struct arc_nft2_be {
  arc_nft2_dims d;
  int id;            /* index in Module.arcSessions */
  int tap;
  char tap_name[96];
};

struct arc_nft2_cache {
  float *ch, *tm;    /* [1, L, cache_ch, d], [1, L, d, conv_cache] */
  int64_t len;
};

static char g_name[64] = "onnxruntime-web";
const char* arc_nft2_be_name(void) { return g_name; }

/* ---- JavaScript side ---- */

EM_ASYNC_JS(int, web_open, (const uint8_t* e0, int n0, const uint8_t* e1, int n1, const uint8_t* dec, int nd,
                            const uint8_t* je, int nje, const uint8_t* jn, int njn, int threads, char* name,
                            char* err, int err_len), {
  const fail = (m) => { stringToUTF8("nft2 web: " + m, err, err_len); return -1; };
  const ort = Module.ort;
  if (!ort || !ort.InferenceSession) return fail("Module.ort (onnxruntime-web) is not set");
  if (!Module.encoderWeights) return fail("Module.encoderWeights (encoder_onnx/encoder.weights) is not set");
  const bytes = (p, n) => HEAPU8.slice(p, p + n);          // copies: the C buffers are freed after the call
  const g0 = n0 ? bytes(e0, n0) : null, g1 = bytes(e1, n1), gd = bytes(dec, nd), gje = bytes(je, nje),
        gjn = bytes(jn, njn);
  const base = { executionProviders: ["wasm"], graphOptimizationLevel: "all", executionMode: "sequential" };
  const enc = { ...base, externalData: [{ path: "encoder.weights", data: Module.encoderWeights }] };
  try {
    const s = {};
    s.enc = await ort.InferenceSession.create(g1, enc);
    s.enc0 = g0 ? await ort.InferenceSession.create(g0, enc) : null;
    s.dec = await ort.InferenceSession.create(gd, base);
    s.jenc = await ort.InferenceSession.create(gje, base);
    s.jnet = await ort.InferenceSession.create(gjn, base);
    Module.arcSessions = Module.arcSessions || [];
    Module.arcSessions.push(s);
    stringToUTF8("onnxruntime-web " + ((ort.env && ort.env.versions && ort.env.versions.web) || "?"), name, 64);
    return Module.arcSessions.length - 1;
  } catch (e) {
    return fail(String(e && e.message || e));
  }
});

EM_JS(void, web_free, (int id), {
  const s = Module.arcSessions && Module.arcSessions[id];
  if (!s) return;
  for (const k of ["enc", "enc0", "dec", "jenc", "jnet"]) if (s[k]) s[k].release();
  Module.arcSessions[id] = null;
});

/* encoder chunk. Out: H raw [1, D, T] -> h (cap D * hcap), tap raw [1, Tt, D] -> tp (cap D * hcap), caches in place,
 * info[0] = T, info[1] = encoded length, info[2] = Tt (tap frames), info[3] = tap's last dim */
EM_ASYNC_JS(int, web_chunk, (int id, int first, const float* xt, int nm, int n, float* ch, int L, int cc, int D,
                             float* tm, int conv, int64_t* clen, const char* tap_name, float* h, float* tp, int hcap,
                             int* info, char* err, int err_len), {
  const s = Module.arcSessions[id], ort = Module.ort;
  const sess = first && s.enc0 ? s.enc0 : s.enc;
  const f32 = (p, n) => HEAPF32.slice(p >> 2, (p >> 2) + n);
  const nch = L * cc * D, ntm = L * D * conv;
  const lenv = BigInt(HEAP32[clen >> 2]);
  const feeds = {
    audio_signal: new ort.Tensor("float32", f32(xt, nm * n), [1, nm, n]),
    length: new ort.Tensor("int64", BigInt64Array.from([BigInt(n)]), [1]),
    cache_last_channel: new ort.Tensor("float32", f32(ch, nch), [1, L, cc, D]),
    cache_last_time: new ort.Tensor("float32", f32(tm, ntm), [1, L, D, conv]),
    cache_last_channel_len: new ort.Tensor("int64", BigInt64Array.from([lenv]), [1]),
  };
  const tapn = tap_name ? UTF8ToString(tap_name) : null;
  const fetches = ["outputs", "encoded_lengths", "cache_last_channel_next", "cache_last_time_next",
                   "cache_last_channel_next_len"];
  if (tapn) fetches.push(tapn);
  let o;
  try {
    o = await sess.run(feeds, fetches);
  } catch (e) {
    stringToUTF8("onnxruntime-web: encoder: " + String(e && e.message || e), err, err_len);
    return -1;
  }
  const H = o.outputs, T = H.dims[2];
  if (H.dims[1] !== D || T > hcap) { stringToUTF8("nft2 web: unexpected encoder output shape", err, err_len); return -1; }
  if (o.cache_last_channel_next.data.length !== nch || o.cache_last_time_next.data.length !== ntm) {
    stringToUTF8("nft2 web: unexpected cache shape", err, err_len);
    return -1;
  }
  HEAPF32.set(H.data, h >> 2);
  HEAPF32.set(o.cache_last_channel_next.data, ch >> 2);
  HEAPF32.set(o.cache_last_time_next.data, tm >> 2);
  const nl = Number(o.cache_last_channel_next_len.data[0]);
  HEAP32[clen >> 2] = nl; HEAP32[(clen >> 2) + 1] = nl < 0 ? -1 : 0;
  HEAP32[info >> 2] = T;
  HEAP32[(info >> 2) + 1] = Number(o.encoded_lengths.data[0]);
  if (tapn) {
    const t = o[tapn];
    if (t.dims.length !== 3 || t.dims[1] > hcap) { stringToUTF8("nft2 web: unexpected tap shape", err, err_len); return -1; }
    HEAPF32.set(t.data, tp >> 2);
    HEAP32[(info >> 2) + 2] = t.dims[1];
    HEAP32[(info >> 2) + 3] = t.dims[2];
  }
  for (const k in o) o[k].dispose && o[k].dispose();
  return 0;
});

/* a one-output net: joint_enc (enc [1, T, D] -> f), joint_net (f, g [n, J] -> logits) */
EM_ASYNC_JS(int, web_joint, (int id, int which, const float* a, int r, int c, const float* b, float* out, int out_n,
                             char* err, int err_len), {
  const s = Module.arcSessions[id], ort = Module.ort;
  const f32 = (p, n) => HEAPF32.slice(p >> 2, (p >> 2) + n);
  let sess, feeds, name;
  if (which === 0) {
    sess = s.jenc; name = "f";
    feeds = { enc: new ort.Tensor("float32", f32(a, r * c), [1, r, c]) };
  } else {
    sess = s.jnet; name = "logits";
    feeds = { f: new ort.Tensor("float32", f32(a, r * c), [r, c]), g: new ort.Tensor("float32", f32(b, r * c), [r, c]) };
  }
  try {
    const o = await sess.run(feeds, [name]);
    if (o[name].data.length !== out_n) throw new Error("unexpected output size " + o[name].data.length);
    HEAPF32.set(o[name].data, out >> 2);
    o[name].dispose && o[name].dispose();
    return 0;
  } catch (e) {
    stringToUTF8("onnxruntime-web: " + (which ? "joint" : "joint_enc") + ": " + String(e && e.message || e), err, err_len);
    return -1;
  }
});

EM_ASYNC_JS(int, web_pred, (int id, int y, float* hc, int layers, int hidden, float* g, int J, char* err, int err_len), {
  const s = Module.arcSessions[id], ort = Module.ort;
  const nh = layers * hidden, p = hc >> 2;
  const feeds = {
    y: new ort.Tensor("int64", BigInt64Array.from([BigInt(y)]), [1, 1]),
    h: new ort.Tensor("float32", HEAPF32.slice(p, p + nh), [layers, 1, hidden]),
    c: new ort.Tensor("float32", HEAPF32.slice(p + nh, p + 2 * nh), [layers, 1, hidden]),
  };
  try {
    const o = await s.dec.run(feeds, ["g", "h_out", "c_out"]);
    if (o.g.data.length !== J) throw new Error("unexpected g size " + o.g.data.length);
    HEAPF32.set(o.g.data, g >> 2);
    HEAPF32.set(o.h_out.data, p);
    HEAPF32.set(o.c_out.data, p + nh);
    for (const k in o) o[k].dispose && o[k].dispose();
    return 0;
  } catch (e) {
    stringToUTF8("onnxruntime-web: decoder: " + String(e && e.message || e), err, err_len);
    return -1;
  }
});

/* ---- the backend interface (arc_nft2_be.h) ---- */

static int read_graph(const char* dir, const char* file, uint8_t** raw, size_t* n) {
  char path[1200];
  char* t = NULL;
  snprintf(path, sizeof path, "%s/%s", dir, file);
  if (arc_read_file(path, &t, n)) return -1;
  *raw = (uint8_t*)t;
  return 0;
}

/* the encoder graph with the tap appended as an output (the external-initializer list is not needed here) */
static int encoder_graph(const char* dir, const char* file, const char* tap, uint8_t** out, size_t* out_n) {
  uint8_t* raw = NULL;
  size_t n = 0;
  arc_onnx_ext* ext = NULL;
  int n_ext = 0;
  if (read_graph(dir, file, &raw, &n)) return -1;
  int rc = arc_onnx_edit_model(raw, n, tap, out, out_n, &ext, &n_ext);
  for (int i = 0; i < n_ext; ++i) free(ext[i].name);
  free(ext);
  arc_free(raw);
  return rc;
}

arc_nft2_be* arc_nft2_be_open(const char* dir, const arc_nft2_dims* dims, int tap, int threads) {
  arc_nft2_be* b = calloc(1, sizeof *b);
  uint8_t *e0 = NULL, *e1 = NULL, *dec = NULL, *je = NULL, *jn = NULL;
  size_t n0 = 0, n1 = 0, nd = 0, nje = 0, njn = 0;
  char err[600] = {0};
  if (!b) return NULL;
  b->d = *dims;
  b->tap = tap;
  b->id = -1;
  if (tap > 0) snprintf(b->tap_name, sizeof b->tap_name, "/layers.%d/norm_out/LayerNormalization_output_0", tap - 1);
  const char* tn = b->tap ? b->tap_name : NULL;
  if (encoder_graph(dir, "encoder.onnx", tn, &e1, &n1) ||
      (dims->first > 0 && encoder_graph(dir, "encoder_first.onnx", tn, &e0, &n0)) ||
      read_graph(dir, "decoder.onnx", &dec, &nd) || read_graph(dir, "joint_enc.onnx", &je, &nje) ||
      read_graph(dir, "joint_net.onnx", &jn, &njn)) {
    if (!arc_geterr()[0]) arc_seterr("nft2 web: cannot read the graphs in %s", dir);
    goto fail;
  }
  b->id = web_open(e0, (int)n0, e1, (int)n1, dec, (int)nd, je, (int)nje, jn, (int)njn, threads, g_name, err,
                   (int)sizeof err);
  if (b->id < 0) {
    arc_seterr("%s", err);
    goto fail;
  }
  free(e0);
  free(e1);
  arc_free(dec);
  arc_free(je);
  arc_free(jn);
  return b;
fail:
  free(e0);
  free(e1);
  arc_free(dec);
  arc_free(je);
  arc_free(jn);
  arc_nft2_be_free(b);
  return NULL;
}

void arc_nft2_be_free(arc_nft2_be* b) {
  if (!b) return;
  if (b->id >= 0) web_free(b->id);
  free(b);
}

arc_nft2_cache* arc_nft2_be_cache_new(arc_nft2_be* b) {
  arc_nft2_cache* c = arc_calloc(sizeof *c);
  if (!c) return NULL;
  const arc_nft2_dims* d = &b->d;
  c->ch = arc_calloc(sizeof(float) * (size_t)d->n_layers * d->cache_ch * d->d_model);
  c->tm = arc_calloc(sizeof(float) * (size_t)d->n_layers * d->d_model * d->conv_cache);
  if (!c->ch || !c->tm) {
    arc_nft2_be_cache_free(c);
    return NULL;
  }
  return c;
}

void arc_nft2_be_cache_free(arc_nft2_cache* c) {
  if (!c) return;
  arc_free(c->ch);
  arc_free(c->tm);
  arc_free(c);
}

#define HCAP 128   /* encoder frames per chunk, at most (65 mel frames / 8 here) */

int arc_nft2_be_chunk(arc_nft2_be* b, arc_nft2_cache* c, int first, const float* x, int n, float* out, float* tap,
                      int cap, int* k) {
  const arc_nft2_dims* d = &b->d;
  int D = d->d_model, nm = d->n_mels, rc = -1;
  char err[600] = {0};
  int info[4] = {0};
  float* xt = arc_malloc(sizeof(float) * (size_t)nm * (n > 0 ? n : 1));
  float* H = arc_malloc(sizeof(float) * (size_t)D * HCAP);
  float* Ht = b->tap ? arc_malloc(sizeof(float) * (size_t)D * HCAP) : NULL;
  if (!xt || !H || (b->tap && !Ht)) goto done;
  for (int t = 0; t < n; ++t)   /* [n, 80] -> [1, 80, n] */
    for (int m = 0; m < nm; ++m) xt[(size_t)m * n + t] = x[(size_t)t * nm + m];
  if (web_chunk(b->id, first, xt, nm, n, c->ch, d->n_layers, d->cache_ch, D, c->tm, d->conv_cache, &c->len,
                b->tap ? b->tap_name : NULL, H, Ht, HCAP, info, err, (int)sizeof err)) {
    arc_seterr("%s", err);
    goto done;
  }
  {
    int Tout = info[0], kk = info[1];
    if (kk > Tout) kk = Tout;
    if (kk > cap) kk = cap;
    if (kk < 0) kk = 0;
    for (int t = 0; t < kk; ++t)   /* [1, 512, T] -> [k, 512] */
      for (int j = 0; j < D; ++j) out[(size_t)t * D + j] = H[(size_t)j * Tout + t];
    if (tap && b->tap) {
      if (info[3] != D) {
        arc_seterr("nft2 web: unexpected tap shape");
        goto done;
      }
      int kt = kk < info[2] ? kk : info[2];
      memcpy(tap, Ht, sizeof(float) * (size_t)kt * D);
      for (int t = kt; t < kk; ++t) memcpy(tap + (size_t)t * D, Ht + (size_t)(kt - 1) * D, sizeof(float) * D);
    }
    *k = kk;
    rc = 0;
  }
done:
  arc_free(xt);
  arc_free(H);
  arc_free(Ht);
  return rc;
}

int arc_nft2_be_joint_enc(arc_nft2_be* b, const float* H, int T, float* F) {
  char err[600] = {0};
  if (web_joint(b->id, 0, H, T, b->d.d_model, NULL, F, T * b->d.joint_hidden, err, (int)sizeof err)) {
    arc_seterr("%s", err);
    return -1;
  }
  return 0;
}

int arc_nft2_be_pred(arc_nft2_be* b, int y, float* hc, float* g) {
  char err[600] = {0};
  if (web_pred(b->id, y, hc, b->d.pred_layers, b->d.pred_hidden, g, b->d.joint_hidden, err, (int)sizeof err)) {
    arc_seterr("%s", err);
    return -1;
  }
  return 0;
}

int arc_nft2_be_joint(arc_nft2_be* b, const float* F, int n, const float* g, float* logits) {
  int J = b->d.joint_hidden, V = b->d.vocab + 1;
  char err[600] = {0};
  float* G = arc_malloc(sizeof(float) * (size_t)n * J);
  if (!G) return -1;
  for (int r = 0; r < n; ++r) memcpy(G + (size_t)r * J, g, sizeof(float) * (size_t)J);
  int rc = web_joint(b->id, 1, F, n, J, G, logits, n * V, err, (int)sizeof err);
  if (rc) arc_seterr("%s", err);
  arc_free(G);
  return rc ? -1 : 0;
}
