/* NFT2 nets on the ONNX Runtime C API (built with make ARC_ORT=/path/to/onnxruntime): encoder_first.onnx /
 * encoder.onnx (cache-aware streaming chunks, one copy of encoder.weights shared by both graphs) with the Arc tap
 * added as an extra graph output in memory, and the RNNT nets decoder.onnx, joint_enc.onnx, joint_net.onnx.
 *
 * The graphs are read as bytes and edited with a few lines of protobuf (no protobuf library): the tap tensor
 * ("/layers.{tap-1}/norm_out/LayerNormalization_output_0") is appended to the graph outputs, and every initializer
 * stored in encoder.weights is handed to ONNX Runtime as an OrtValue over the memory-mapped file (AddInitializer),
 * so the two encoder sessions share the weights and the prepacked int8 matrices (one prepacked-weights container).
 * Part of arc_transcriber (Whissle Inc.), CC BY-NC 4.0; see LICENSE. */
#define _POSIX_C_SOURCE 200809L
#include "arc_nft2_be.h"

#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include "arc_onnx_pb.h"
#include "onnxruntime_c_api.h"

static const OrtApi* g_ort;
static OrtEnv* g_env;
static int g_env_refs;
static pthread_mutex_t g_env_mu = PTHREAD_MUTEX_INITIALIZER;

const char* arc_nft2_be_name(void) {
  static char name[64];
  if (!name[0]) snprintf(name, sizeof name, "onnxruntime %s", OrtGetApiBase()->GetVersionString());
  return name;
}

static int ok(OrtStatus* s, const char* what) {
  if (!s) return 0;
  arc_seterr("onnxruntime: %s: %s", what, g_ort->GetErrorMessage(s));
  g_ort->ReleaseStatus(s);
  return -1;
}
#define ORT(call, what) \
  do {                  \
    if (ok((call), what)) goto fail; \
  } while (0)

/* ------------------------------------------------------------------ backend */

struct arc_nft2_be {
  arc_nft2_dims d;
  OrtMemoryInfo* mem;
  OrtSession *enc, *enc0, *dec, *jenc, *jnet;
  OrtPrepackedWeightsContainer* pack;
  /* encoder.weights, mapped; one OrtValue per external initializer, shared by both encoder sessions */
  void* map;
  size_t map_len;
  arc_onnx_ext* ext;
  int n_ext;
  OrtValue** ext_val;
  char tap_name[96];
  int tap;
};

struct arc_nft2_cache {
  float *ch, *tm;    /* [1, L, cache_ch, d], [1, L, d, conv_cache] */
  int64_t len;
};

static int read_all(const char* path, uint8_t** data, size_t* n) {
  char* t = NULL;
  if (arc_read_file(path, &t, n)) return -1;
  *data = (uint8_t*)t;
  return 0;
}

static OrtSessionOptions* session_options(int threads, const char* dir) {
  OrtSessionOptions* so = NULL;
  if (ok(g_ort->CreateSessionOptions(&so), "session options")) return NULL;
  if (ok(g_ort->SetIntraOpNumThreads(so, threads), "threads") || ok(g_ort->SetInterOpNumThreads(so, 1), "threads") ||
      ok(g_ort->SetSessionExecutionMode(so, ORT_SEQUENTIAL), "execution mode") ||
      ok(g_ort->SetSessionGraphOptimizationLevel(so, ORT_ENABLE_ALL), "optimization level") ||
      (dir && ok(g_ort->AddSessionConfigEntry(so, "session.model_external_initializers_file_folder_path", dir),
                 "external data folder"))) {
    g_ort->ReleaseSessionOptions(so);
    return NULL;
  }
  return so;
}

static OrtSession* encoder_session(arc_nft2_be* b, const char* dir, const char* file, int threads) {
  char path[1200];
  snprintf(path, sizeof path, "%s/%s", dir, file);
  uint8_t *raw = NULL, *ed = NULL;
  size_t n = 0, ne = 0;
  arc_onnx_ext* ext = NULL;
  int n_ext = 0;
  OrtSession* s = NULL;
  OrtSessionOptions* so = NULL;
  if (read_all(path, &raw, &n)) return NULL;
  if (arc_onnx_edit_model(raw, n, b->tap ? b->tap_name : NULL, &ed, &ne, &ext, &n_ext)) {
    if (!arc_geterr()[0]) arc_seterr("nft2 onnx: cannot read %s", path);
    goto done;
  }
  if (!(so = session_options(threads, dir))) goto done;
  for (int i = 0; i < n_ext; ++i) {
    /* the shared OrtValue for this tensor (same name, offset and length in both graphs) */
    int k = -1;
    for (int j = 0; j < b->n_ext && k < 0; ++j)
      if (!strcmp(b->ext[j].name, ext[i].name) && b->ext[j].offset == ext[i].offset && b->ext[j].length == ext[i].length)
        k = j;
    if (k < 0) {
      if (ext[i].offset + ext[i].length > b->map_len) {
        arc_seterr("nft2 onnx: %s lies outside encoder.weights", ext[i].name);
        goto done;
      }
      arc_onnx_ext* ne2 = realloc(b->ext, sizeof(arc_onnx_ext) * (size_t)(b->n_ext + 1));
      OrtValue** nv = realloc(b->ext_val, sizeof(OrtValue*) * (size_t)(b->n_ext + 1));
      if (!ne2 || !nv) goto done;
      b->ext = ne2;
      b->ext_val = nv;
      k = b->n_ext;
      b->ext[k] = ext[i];
      b->ext[k].name = strdup(ext[i].name);
      b->ext_val[k] = NULL;
      b->n_ext++;
      if (ok(g_ort->CreateTensorWithDataAsOrtValue(b->mem, (uint8_t*)b->map + ext[i].offset, ext[i].length,
                                                   ext[i].dims, (size_t)ext[i].ndim,
                                                   (ONNXTensorElementDataType)ext[i].dtype, &b->ext_val[k]),
             ext[i].name))
        goto done;
    }
    if (ok(g_ort->AddInitializer(so, b->ext[k].name, b->ext_val[k]), "add initializer")) goto done;
  }
  if (ok(g_ort->CreateSessionFromArrayWithPrepackedWeightsContainer(g_env, ed, ne, so, b->pack, &s), path)) s = NULL;
done:
  if (so) g_ort->ReleaseSessionOptions(so);
  for (int i = 0; i < n_ext; ++i) free(ext[i].name);
  free(ext);
  free(ed);
  arc_free(raw);
  return s;
}

static OrtSession* plain_session(const char* dir, const char* file) {
  char path[1200];
  snprintf(path, sizeof path, "%s/%s", dir, file);
  /* Outpost Luna: from memory, not by path (ORTCHAR_T is wchar_t on Windows); see NOTICE */
  uint8_t* raw = NULL;
  size_t n = 0;
  if (read_all(path, &raw, &n)) return NULL;
  OrtSessionOptions* so = session_options(1, NULL);
  if (!so) {
    arc_free(raw);
    return NULL;
  }
  OrtSession* s = NULL;
  if (ok(g_ort->CreateSessionFromArray(g_env, raw, n, so, &s), path)) s = NULL;
  g_ort->ReleaseSessionOptions(so);
  arc_free(raw);
  return s;
}

arc_nft2_be* arc_nft2_be_open(const char* dir, const arc_nft2_dims* dims, int tap, int threads) {
  pthread_mutex_lock(&g_env_mu);
  if (!g_ort) g_ort = OrtGetApiBase()->GetApi(ORT_API_VERSION);
  if (!g_ort) {
    pthread_mutex_unlock(&g_env_mu);
    arc_seterr("onnxruntime: API version %d not available (library %s)", ORT_API_VERSION,
               OrtGetApiBase()->GetVersionString());
    return NULL;
  }
  if (!g_env) {
    if (ok(g_ort->CreateEnv(ORT_LOGGING_LEVEL_ERROR, "arc", &g_env), "env")) {
      pthread_mutex_unlock(&g_env_mu);
      return NULL;
    }
    /* no telemetry: ONNX Runtime's event tracing (Windows ETW builds) is switched off for this process' env */
    OrtStatus* st = g_ort->DisableTelemetryEvents(g_env);
    if (st) g_ort->ReleaseStatus(st);
  }
  g_env_refs++;
  pthread_mutex_unlock(&g_env_mu);
  arc_nft2_be* b = calloc(1, sizeof *b);
  if (!b) {
    arc_nft2_be_free(b);
    return NULL;
  }
  b->d = *dims;
  b->tap = tap;
  if (tap > 0) snprintf(b->tap_name, sizeof b->tap_name, "/layers.%d/norm_out/LayerNormalization_output_0", tap - 1);
  if (threads < 1) threads = 1;
  ORT(g_ort->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault, &b->mem), "memory info");
  ORT(g_ort->CreatePrepackedWeightsContainer(&b->pack), "prepacked weights");
  char path[1200];
  snprintf(path, sizeof path, "%s/encoder.weights", dir);
  int fd = open(path, O_RDONLY);
  struct stat st;
  if (fd < 0 || fstat(fd, &st)) {
    if (fd >= 0) close(fd);
    arc_seterr("nft2 onnx: cannot open %s", path);
    goto fail;
  }
  b->map_len = (size_t)st.st_size;
  b->map = mmap(NULL, b->map_len, PROT_READ, MAP_PRIVATE, fd, 0);
  close(fd);
  if (b->map == MAP_FAILED) {
    b->map = NULL;
    arc_seterr("nft2 onnx: cannot map %s", path);
    goto fail;
  }
  if (!(b->enc = encoder_session(b, dir, "encoder.onnx", threads))) goto fail;
  if (dims->first > 0 && !(b->enc0 = encoder_session(b, dir, "encoder_first.onnx", threads))) goto fail;
  if (!(b->dec = plain_session(dir, "decoder.onnx")) || !(b->jenc = plain_session(dir, "joint_enc.onnx")) ||
      !(b->jnet = plain_session(dir, "joint_net.onnx")))
    goto fail;
  return b;
fail:
  arc_nft2_be_free(b);
  return NULL;
}

void arc_nft2_be_free(arc_nft2_be* b) {
  if (b) {
    OrtSession* ss[5] = {b->enc, b->enc0, b->dec, b->jenc, b->jnet};
    for (int i = 0; i < 5; ++i)
      if (ss[i]) g_ort->ReleaseSession(ss[i]);
    for (int i = 0; i < b->n_ext; ++i) {
      if (b->ext_val[i]) g_ort->ReleaseValue(b->ext_val[i]);
      free(b->ext[i].name);
    }
    free(b->ext);
    free(b->ext_val);
    if (b->pack) g_ort->ReleasePrepackedWeightsContainer(b->pack);
    if (b->mem) g_ort->ReleaseMemoryInfo(b->mem);
    if (b->map) munmap(b->map, b->map_len);
    free(b);
  }
  pthread_mutex_lock(&g_env_mu);
  if (g_env_refs > 0 && --g_env_refs == 0 && g_env) {
    g_ort->ReleaseEnv(g_env);
    g_env = NULL;
  }
  pthread_mutex_unlock(&g_env_mu);
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

static OrtValue* tensor(arc_nft2_be* b, void* p, size_t bytes, const int64_t* shape, int nd, ONNXTensorElementDataType t) {
  OrtValue* v = NULL;
  if (ok(g_ort->CreateTensorWithDataAsOrtValue(b->mem, p, bytes, shape, (size_t)nd, t, &v), "tensor")) return NULL;
  return v;
}

static float* fdata(OrtValue* v) {
  void* p = NULL;
  if (ok(g_ort->GetTensorMutableData(v, &p), "output")) return NULL;
  return p;
}

static int dims_of(OrtValue* v, int64_t* d, int cap) {
  OrtTensorTypeAndShapeInfo* info = NULL;
  size_t n = 0;
  if (ok(g_ort->GetTensorTypeAndShape(v, &info), "shape")) return -1;
  if (ok(g_ort->GetDimensionsCount(info, &n), "shape") || (int)n > cap ||
      ok(g_ort->GetDimensions(info, d, n), "shape")) {
    g_ort->ReleaseTensorTypeAndShapeInfo(info);
    return -1;
  }
  g_ort->ReleaseTensorTypeAndShapeInfo(info);
  return (int)n;
}

int arc_nft2_be_chunk(arc_nft2_be* b, arc_nft2_cache* c, int first, const float* x, int n, float* out, float* tap,
                      int cap, int* k) {
  const arc_nft2_dims* d = &b->d;
  int L = d->n_layers, D = d->d_model, nm = d->n_mels, rc = -1;
  OrtSession* s = first && b->enc0 ? b->enc0 : b->enc;
  float* xt = arc_malloc(sizeof(float) * (size_t)nm * (n > 0 ? n : 1));
  if (!xt) return -1;
  for (int t = 0; t < n; ++t)   /* [n, 80] -> [1, 80, n] */
    for (int m = 0; m < nm; ++m) xt[(size_t)m * n + t] = x[(size_t)t * nm + m];
  int64_t len = n;
  int64_t sh_x[3] = {1, nm, n}, sh_l[1] = {1}, sh_ch[4] = {1, L, d->cache_ch, D}, sh_tm[4] = {1, L, D, d->conv_cache};
  OrtValue* in[5] = {tensor(b, xt, sizeof(float) * (size_t)nm * n, sh_x, 3, ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT),
                     tensor(b, &len, sizeof len, sh_l, 1, ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64),
                     tensor(b, c->ch, sizeof(float) * (size_t)L * d->cache_ch * D, sh_ch, 4, ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT),
                     tensor(b, c->tm, sizeof(float) * (size_t)L * D * d->conv_cache, sh_tm, 4, ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT),
                     tensor(b, &c->len, sizeof c->len, sh_l, 1, ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64)};
  const char* in_names[5] = {"audio_signal", "length", "cache_last_channel", "cache_last_time", "cache_last_channel_len"};
  const char* out_names[6] = {"outputs", "encoded_lengths", "cache_last_channel_next", "cache_last_time_next",
                              "cache_last_channel_next_len", b->tap_name};
  OrtValue* o[6] = {0};
  int no = b->tap ? 6 : 5;
  for (int i = 0; i < 5; ++i)
    if (!in[i]) goto done;
  if (ok(g_ort->Run(s, NULL, in_names, (const OrtValue* const*)in, 5, out_names, (size_t)no, o), "encoder")) goto done;
  {
    int64_t sd[4];
    if (dims_of(o[0], sd, 4) != 3) goto done;
    int Tout = (int)sd[2];
    const int64_t* ol = (const int64_t*)fdata(o[1]);
    const float *H = fdata(o[0]), *nch = fdata(o[2]), *ntm = fdata(o[3]);
    const int64_t* nlen = (const int64_t*)fdata(o[4]);
    if (!ol || !H || !nch || !ntm || !nlen) goto done;
    int kk = (int)ol[0];
    if (kk > Tout) kk = Tout;
    if (kk > cap) kk = cap;
    if (kk < 0) kk = 0;
    for (int t = 0; t < kk; ++t)   /* [1, 512, T] -> [k, 512] */
      for (int j = 0; j < D; ++j) out[(size_t)t * D + j] = H[(size_t)j * Tout + t];
    if (tap && b->tap) {
      int64_t td[4];
      if (dims_of(o[5], td, 4) != 3) goto done;
      const float* Ht = fdata(o[5]);
      if (!Ht || td[2] != D) goto done;
      int kt = kk < (int)td[1] ? kk : (int)td[1];
      memcpy(tap, Ht, sizeof(float) * (size_t)kt * D);
      for (int t = kt; t < kk; ++t) memcpy(tap + (size_t)t * D, Ht + (size_t)(kt - 1) * D, sizeof(float) * D);
    }
    int64_t cd[4];
    if (dims_of(o[2], cd, 4) != 4 || cd[1] != L || cd[2] != d->cache_ch || cd[3] != D) {
      arc_seterr("nft2 onnx: unexpected cache shape");
      goto done;
    }
    memcpy(c->ch, nch, sizeof(float) * (size_t)L * d->cache_ch * D);
    if (dims_of(o[3], cd, 4) != 4 || cd[3] != d->conv_cache) {
      arc_seterr("nft2 onnx: unexpected conv cache shape");
      goto done;
    }
    memcpy(c->tm, ntm, sizeof(float) * (size_t)L * D * d->conv_cache);
    c->len = nlen[0];
    *k = kk;
    rc = 0;
  }
done:
  for (int i = 0; i < 5; ++i)
    if (in[i]) g_ort->ReleaseValue(in[i]);
  for (int i = 0; i < 6; ++i)
    if (o[i]) g_ort->ReleaseValue(o[i]);
  arc_free(xt);
  return rc;
}

int arc_nft2_be_joint_enc(arc_nft2_be* b, const float* H, int T, float* F) {
  int64_t sh[3] = {1, T, b->d.d_model};
  OrtValue* in = tensor(b, (void*)H, sizeof(float) * (size_t)T * b->d.d_model, sh, 3, ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT);
  OrtValue* o = NULL;
  const char *in_n = "enc", *out_n = "f";
  int rc = -1;
  if (in && !ok(g_ort->Run(b->jenc, NULL, &in_n, (const OrtValue* const*)&in, 1, &out_n, 1, &o), "joint_enc")) {
    const float* f = fdata(o);
    if (f) {
      memcpy(F, f, sizeof(float) * (size_t)T * b->d.joint_hidden);
      rc = 0;
    }
  }
  if (in) g_ort->ReleaseValue(in);
  if (o) g_ort->ReleaseValue(o);
  return rc;
}

int arc_nft2_be_pred(arc_nft2_be* b, int y, float* hc, float* g) {
  const arc_nft2_dims* d = &b->d;
  size_t nh = (size_t)d->pred_layers * d->pred_hidden;
  int64_t yy = y, sh_y[2] = {1, 1}, sh_h[3] = {d->pred_layers, 1, d->pred_hidden};
  OrtValue* in[3] = {tensor(b, &yy, sizeof yy, sh_y, 2, ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64),
                     tensor(b, hc, sizeof(float) * nh, sh_h, 3, ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT),
                     tensor(b, hc + nh, sizeof(float) * nh, sh_h, 3, ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT)};
  const char* in_n[3] = {"y", "h", "c"};
  const char* out_n[3] = {"g", "h_out", "c_out"};
  OrtValue* o[3] = {0};
  int rc = -1;
  if (in[0] && in[1] && in[2] && !ok(g_ort->Run(b->dec, NULL, in_n, (const OrtValue* const*)in, 3, out_n, 3, o), "decoder")) {
    const float *gg = fdata(o[0]), *h = fdata(o[1]), *c = fdata(o[2]);
    if (gg && h && c) {
      memcpy(g, gg, sizeof(float) * (size_t)d->joint_hidden);
      memcpy(hc, h, sizeof(float) * nh);
      memcpy(hc + nh, c, sizeof(float) * nh);
      rc = 0;
    }
  }
  for (int i = 0; i < 3; ++i) {
    if (in[i]) g_ort->ReleaseValue(in[i]);
    if (o[i]) g_ort->ReleaseValue(o[i]);
  }
  return rc;
}

int arc_nft2_be_joint(arc_nft2_be* b, const float* F, int n, const float* g, float* logits) {
  int J = b->d.joint_hidden, V = b->d.vocab + 1;
  float* G = arc_malloc(sizeof(float) * (size_t)n * J);
  if (!G) return -1;
  for (int r = 0; r < n; ++r) memcpy(G + (size_t)r * J, g, sizeof(float) * (size_t)J);
  int64_t sh[2] = {n, J};
  OrtValue* in[2] = {tensor(b, (void*)F, sizeof(float) * (size_t)n * J, sh, 2, ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT),
                     tensor(b, G, sizeof(float) * (size_t)n * J, sh, 2, ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT)};
  const char* in_n[2] = {"f", "g"};
  const char* out_n = "logits";
  OrtValue* o = NULL;
  int rc = -1;
  if (in[0] && in[1] && !ok(g_ort->Run(b->jnet, NULL, in_n, (const OrtValue* const*)in, 2, &out_n, 1, &o), "joint")) {
    const float* l = fdata(o);
    if (l) {
      memcpy(logits, l, sizeof(float) * (size_t)n * V);
      rc = 0;
    }
  }
  for (int i = 0; i < 2; ++i)
    if (in[i]) g_ort->ReleaseValue(in[i]);
  if (o) g_ort->ReleaseValue(o);
  arc_free(G);
  return rc;
}
