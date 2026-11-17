/* Fuzz libarc's Arc Transcriber Space C API (arc.h: arc_nft2_*) under AddressSanitizer + UBSan.
 * Release gate 4a (docs/RELEASING.md, desktop/scripts/release_check.py builds and runs it).
 *
 * Each input drives a short random program against ONE loaded model: names lists (unicode, empty, huge, odd kinds,
 * many aliases), context prompts, whole-clip transcribes and streams (feed / flush / close) with random PCM lengths
 * and values (silence, noise, a tone, full-scale, denormals, NaN / Inf). Every string of every result is read, so a
 * dangling or unterminated pointer shows up under ASan.
 *
 * Two drivers, one body (fuzz_one):
 *   standalone (default)    fuzz_libarc <nft2 dir> <libonnxruntime path> [seconds] [seed]
 *                           random inputs from a seeded PRNG until the time box ends; prints the seed and counts
 *   libFuzzer               cc -DARC_LIBFUZZER -fsanitize=fuzzer,address ... (needs an LLVM with libFuzzer; Apple
 *                           clang has none). ARC_NFT2_DIR / ARC_ORT_LIB give the model and the runtime.
 * The API contract is respected (a non-NULL model, valid UTF-8 strings as the Python binding sends): we look for
 * memory errors and crashes inside libarc, not for misuse. ARC_FUZZ_RAW=1 also sends arbitrary (non-UTF-8) bytes.
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "arc.h"

static arc_nft2* M = NULL;
static int RAW = 0;
static long N_CALLS = 0, N_RESULTS = 0, N_NULL = 0;

/* ---- a byte reader over the input (libFuzzer) or a PRNG (standalone): both give the same fuzz_one ---- */
typedef struct {
  const uint8_t* d;
  size_t n, i;
  uint64_t s;   /* PRNG state when d == NULL */
} src_t;

static uint64_t rnd64(src_t* r) {
  if (r->d) {
    uint64_t v = 0;
    for (int k = 0; k < 8; k++) v = (v << 8) | (r->i < r->n ? r->d[r->i++] : 0);
    return v;
  }
  r->s ^= r->s << 13; r->s ^= r->s >> 7; r->s ^= r->s << 17;   /* xorshift64 */
  return r->s;
}
static uint32_t rn(src_t* r, uint32_t n) { return n ? (uint32_t)(rnd64(r) % n) : 0; }
static int done(src_t* r) { return r->d && r->i >= r->n; }

/* ---- strings ---- */
static const char* WORDS[] = {"Shackleton", "de Gerlache", "Orientale Basin", "Artemis II", "CAPCOM", "Tycho",
  "Mare Tranquillitatis", "South Pole\xe2\x80\x93" "Aitken Basin", "Tsiolkovskiy", "\xc3\x89" "cole", "\xe6\x9c\x88",
  "\xf0\x9f\x9a\x80 rover", "a", "", " ", "  x  ", "Apollo 16 rover", "Reid Wiseman", "\xd0\x9b\xd1\x83\xd0\xbd\xd0\xb0",
  "\xe0\xa4\x9a\xe0\xa4\x82\xe0\xa4\xa6\xe0\xa5\x8d\xe0\xa4\xb0", "O'Brien-Smith", "1969", "%s%n%x", "\\\"quoted\\\""};
static const char* KINDS[] = {"lunar_feature", "site", "celestial", "spacecraft", "vehicle", "mission", "crew",
  "person", "place", "organization", "product", "team", "law", "", "not_a_kind", NULL};
#define NW (sizeof WORDS / sizeof *WORDS)
#define NK (sizeof KINDS / sizeof *KINDS)

/* A fresh heap string (freed by the caller): a known word, random UTF-8, a long run, or raw bytes. */
static char* rstr(src_t* r) {
  uint32_t mode = rn(r, 10);
  size_t len;
  char* s;
  if (mode < 5) return strdup(WORDS[rn(r, NW)]);
  if (mode < 8) {                                   /* random valid UTF-8, 0..64 code points */
    size_t cps = rn(r, 65);
    s = malloc(cps * 4 + 1);
    len = 0;
    for (size_t k = 0; k < cps; k++) {
      uint32_t c;
      switch (rn(r, 4)) {
        case 0: c = 0x20 + rn(r, 0x5f); break;                       /* ASCII */
        case 1: c = 0x80 + rn(r, 0x780); break;                      /* 2 bytes */
        case 2: c = 0x800 + rn(r, 0xF800); if (c >= 0xD800 && c < 0xE000) c = 0x41; break;
        default: c = 0x10000 + rn(r, 0x100000); break;               /* 4 bytes (emoji, CJK ext) */
      }
      if (c < 0x80) s[len++] = (char)c;
      else if (c < 0x800) { s[len++] = (char)(0xC0 | (c >> 6)); s[len++] = (char)(0x80 | (c & 63)); }
      else if (c < 0x10000) { s[len++] = (char)(0xE0 | (c >> 12)); s[len++] = (char)(0x80 | ((c >> 6) & 63));
                              s[len++] = (char)(0x80 | (c & 63)); }
      else { s[len++] = (char)(0xF0 | (c >> 18)); s[len++] = (char)(0x80 | ((c >> 12) & 63));
             s[len++] = (char)(0x80 | ((c >> 6) & 63)); s[len++] = (char)(0x80 | (c & 63)); }
    }
    s[len] = 0;
    return s;
  }
  if (mode < 9 || !RAW) {                          /* a long name: 1..8 KB of one repeated word */
    const char* w = WORDS[rn(r, NW)];
    size_t wl = strlen(w) + 1, reps = 1 + rn(r, 8192 / (wl ? wl : 1));
    s = malloc(reps * wl + 1);
    len = 0;
    for (size_t k = 0; k < reps; k++) { memcpy(s + len, w, wl - 1); len += wl - 1; s[len++] = ' '; }
    s[len] = 0;
    return s;
  }
  len = rn(r, 256);                                /* raw bytes (ARC_FUZZ_RAW=1 only) */
  s = malloc(len + 1);
  for (size_t k = 0; k < len; k++) { s[k] = (char)(1 + rn(r, 255)); }
  s[len] = 0;
  return s;
}

/* ---- results: touch everything ---- */
static size_t touch(const char* s) { return s ? strlen(s) : 0; }
static size_t walk(const arc_result* res) {
  size_t h = 0;
  if (!res) { N_NULL++; return 0; }
  N_RESULTS++;
  for (int i = 0; i < res->n_utts; i++) {
    const arc_utt* u = &res->utts[i];
    h += touch(u->text) + touch(u->decoder_text) + touch(u->intent.label) + touch(u->act.label);
    for (int k = 0; k < u->n_tags; k++) h += touch(u->tags[k].tag) + touch(u->tags[k].text) + (size_t)u->tags[k].word_end;
    for (int k = 0; k < u->n_words; k++) {
      const arc_word* w = &u->words[k];
      h += touch(w->text) + touch(w->tag) + touch(w->disfl) + (size_t)(w->conf > 2.0f);
      for (int j = 0; j < w->n_alts; j++) h += touch(w->alts[j]) + (size_t)(w->alt_p ? w->alt_p[j] > 2.0f : 0);
    }
    for (int k = 0; k < u->n_alts; k++) h += touch(u->alts[k]) + (size_t)(u->alt_scores ? u->alt_scores[k] != 0 : 0);
    /* ABI 2 read-outs */
    h += touch(u->clean_text) + touch(u->tagger_json) + (size_t)u->n_dropped + (size_t)(u->playback_leak > 2.0f);
    for (int k = 0; k < u->n_quantities; k++)
      h += touch(u->quantities[k].type) + touch(u->quantities[k].unit) + touch(u->quantities[k].text) +
           touch(u->quantities[k].written) + (size_t)(u->quantities[k].word_end - u->quantities[k].word_begin);
  }
  for (int i = 0; i < res->n_names; i++) {
    const arc_name* n = &res->names[i];
    h += touch(n->tag) + touch(n->heard) + touch(n->entity) + touch(n->state) + touch(n->src) + touch(n->via)
       + touch(n->model_entity) + touch(n->candidate) + (size_t)(n->candidate_kb_index + 1);
    for (int k = 0; k < n->n_words; k++) h += touch(n->words[k].text);
  }
  for (int i = 0; i < res->n_numbers; i++) {
    const arc_number* n = &res->numbers[i];
    h += touch(n->kind) + touch(n->unit) + touch(n->heard) + touch(n->state) + touch(n->kind_head);
  }
  for (int i = 0; i < res->n_events; i++) h += touch(res->events[i].label);
  return h;
}

/* ---- audio ---- */
static float* rpcm(src_t* r, size_t* n) {
  static const size_t LENS[] = {0, 1, 2, 159, 160, 1280, 1281, 4000, 8000, 16000, 24001, 48000, 80000};
  size_t len = rn(r, 3) ? LENS[rn(r, sizeof LENS / sizeof *LENS)] : rn(r, 48000);   /* <= 3 s */
  float* x = malloc((len ? len : 1) * sizeof(float));
  uint32_t kind = rn(r, 8);
  float f = 80.0f + (float)rn(r, 3000), amp = (float)rn(r, 1000) / 1000.0f;
  for (size_t i = 0; i < len; i++) {
    switch (kind) {
      case 0: x[i] = 0.0f; break;
      case 1: x[i] = ((float)rn(r, 65536) / 32768.0f - 1.0f) * amp; break;           /* noise */
      case 2: x[i] = amp * sinf(6.2831853f * f * (float)i / 16000.0f); break;          /* tone */
      case 3: x[i] = (i & 1) ? 1.0f : -1.0f; break;                                    /* full scale */
      case 4: x[i] = 1e-40f; break;                                                    /* denormal */
      case 5: x[i] = rn(r, 50) ? amp * sinf((float)i * 0.01f) : NAN; break;           /* NaN drops */
      case 6: x[i] = rn(r, 50) ? 0.1f : (rn(r, 2) ? INFINITY : -INFINITY); break;
      default: x[i] = ((float)rn(r, 65536) - 32768.0f) * 1000.0f; break;              /* way out of range */
    }
  }
  *n = len;
  return x;
}

/* ---- ops ---- */
static void op_names(src_t* r) {
  int n = (int)(rn(r, 4) == 0 ? rn(r, 2000) : rn(r, 50));   /* 0 clears; up to 2000 names */
  arc_name_entry* e = calloc((size_t)(n ? n : 1), sizeof *e);
  char** keep = calloc((size_t)(n ? n : 1) * 20, sizeof(char*));
  const char*** al = calloc((size_t)(n ? n : 1), sizeof(char**));
  int nk = 0;
  for (int i = 0; i < n; i++) {
    e[i].name = keep[nk++] = rstr(r);
    e[i].kind = KINDS[rn(r, NK)];
    e[i].group = rn(r, 4) ? NULL : (keep[nk++] = rstr(r));
    int na = (int)rn(r, 4) == 0 ? (int)rn(r, 16) : 0;
    al[i] = calloc((size_t)(na ? na : 1), sizeof(char*));
    for (int k = 0; k < na; k++) al[i][k] = keep[nk++] = rstr(r);
    e[i].aliases = na ? al[i] : NULL;
    e[i].n_aliases = na;
  }
  N_CALLS++;
  (void)arc_nft2_set_names(M, e, n);
  for (int i = 0; i < nk; i++) free(keep[i]);
  for (int i = 0; i < n; i++) free((void*)al[i]);
  free(al); free(keep); free(e);
}

static void op_context(src_t* r) {
  if (rn(r, 5) == 0) { N_CALLS++; (void)arc_nft2_set_context(M, NULL); return; }
  arc_nft2_context c;
  memset(&c, 0, sizeof c);
  char* s[64];
  int ns = 0;
  c.dom = rn(r, 3) ? NULL : (s[ns++] = rstr(r));
  c.prev = rn(r, 2) ? NULL : (s[ns++] = rstr(r));
  c.auto_prev = (int)rn(r, 2);
  const char* kb[8]; const char* kk[8];
  c.n_kb = (int)rn(r, 9);
  for (int i = 0; i < c.n_kb; i++) { kb[i] = s[ns++] = rstr(r); kk[i] = KINDS[rn(r, NK)]; }
  c.kb = c.n_kb ? kb : NULL;
  c.kb_kind = c.n_kb && rn(r, 2) ? kk : NULL;
  arc_nft2_ses_speaker sp[4]; arc_nft2_ses_number nu[6]; arc_nft2_ses_entity en[6];
  c.n_speakers = (int)rn(r, 5);
  for (int i = 0; i < c.n_speakers; i++) { sp[i].slot = s[ns++] = rstr(r); sp[i].role = rn(r, 2) ? "device_user" : NULL; }
  c.speakers = c.n_speakers ? sp : NULL;
  c.n_numbers = (int)rn(r, 7);
  for (int i = 0; i < c.n_numbers; i++) { nu[i].value = s[ns++] = rstr(r); nu[i].kind = rn(r, 2) ? "count" : NULL;
                                          nu[i].minutes = (int)rn(r, 100000) - 1; }
  c.numbers = c.n_numbers ? nu : NULL;
  c.n_entities = (int)rn(r, 7);
  for (int i = 0; i < c.n_entities; i++) { en[i].surface = s[ns++] = rstr(r); en[i].type = rn(r, 2) ? "place" : NULL;
                                           en[i].minutes = (int)rn(r, 100) - 1; }
  c.entities = c.n_entities ? en : NULL;
  N_CALLS++;
  (void)arc_nft2_set_context(M, &c);
  for (int i = 0; i < ns; i++) free(s[i]);
}

static arc_nft2_options ropts(src_t* r, arc_nft2_options* o) {
  static const char* DOMS[] = {NULL, "assistant", "news", "talk", "", "nope"};
  memset(o, 0, sizeof *o);
  o->domain = DOMS[rn(r, 6)];
  o->no_bias = (int)rn(r, 2);
  o->no_events = (int)rn(r, 2);
  /* ABI 2 */
  o->no_guard = (int)rn(r, 4) == 0;
  o->almost = (int)rn(r, 2);
  o->nbest = (int)(rn(r, 3) ? rn(r, 6) : rn(r, 40));
  o->live = (int)rn(r, 2);
  o->playback_threshold = rn(r, 4) ? 0.0f : (float)rn(r, 1200) / 1000.0f;
  o->playback_drop = (int)rn(r, 2);
  o->echo_decode = (int)rn(r, 2);
  return *o;
}

static void op_transcribe(src_t* r) {
  size_t n;
  float* x = rpcm(r, &n);
  arc_nft2_options o;
  ropts(r, &o);
  N_CALLS++;
  arc_result* res = arc_nft2_transcribe(M, x, n, rn(r, 3) ? &o : NULL);
  walk(res);
  if (res) arc_result_free(res);
  free(x);
}

static size_t walk_events(arc_nft2_stream* st) {
  int n = -1;
  const arc_nft2_event* ev = arc_nft2_stream_events(st, &n);
  size_t h = 0;
  for (int i = 0; ev && i < n; i++)
    h += touch(ev[i].text) + touch(ev[i].kind) + touch(ev[i].entity) + touch(ev[i].qtype) + touch(ev[i].unit) +
         (size_t)(ev[i].type + ev[i].n_stable + ev[i].kb_index + ev[i].relative);
  return h;
}

static void op_stream_names(src_t* r, arc_nft2_stream* st) {
  int n = (int)rn(r, 30);
  arc_name_entry* e = calloc((size_t)(n ? n : 1), sizeof *e);
  char** keep = calloc((size_t)(n ? n : 1), sizeof(char*));
  for (int i = 0; i < n; i++) { e[i].name = keep[i] = rstr(r); e[i].kind = KINDS[rn(r, NK)]; }
  N_CALLS++;
  (void)arc_nft2_stream_set_names(st, e, n);
  for (int i = 0; i < n; i++) free(keep[i]);
  free(keep); free(e);
}

static void op_stream(src_t* r) {
  arc_nft2_options o;
  ropts(r, &o);
  N_CALLS++;
  arc_nft2_stream* st = arc_nft2_stream_open(M, rn(r, 3) ? &o : NULL);
  if (!st) { N_NULL++; return; }
  int feeds = (int)rn(r, 12);
  for (int i = 0; i < feeds && !done(r); i++) {
    if (rn(r, 6) == 0) op_names(r);              /* the list changes mid-stream (a screen change) */
    if (rn(r, 6) == 0) op_stream_names(r, st);   /* ABI 2: arc_nft2_stream_set_names */
    if (rn(r, 3) == 0) {                         /* ABI 2: the playback reference, at any time (also < 0, NaN) */
      size_t nr;
      float* y = rpcm(r, &nr);
      double t = rn(r, 4) == 0 ? -1.0 : rn(r, 8) == 0 ? (double)NAN : (double)rn(r, 20000) / 1000.0 - 2.0;
      N_CALLS++;
      (void)arc_nft2_stream_feed_ref(st, y, nr, t);
      free(y);
    }
    size_t n;
    float* x = rpcm(r, &n);
    N_CALLS++;
    arc_result* res = arc_nft2_stream_feed(st, x, n);
    walk(res);
    if (res) arc_result_free(res);
    walk_events(st);
    free(x);
    if (rn(r, 8) == 0) {                         /* ABI 2: push-to-talk release */
      N_CALLS++;
      res = arc_nft2_stream_end_turn(st);
      walk(res);
      if (res) arc_result_free(res);
      walk_events(st);
    }
  }
  if (rn(r, 4)) {
    N_CALLS++;
    arc_result* res = arc_nft2_stream_flush(st);
    walk(res);
    if (res) arc_result_free(res);
    if (rn(r, 4) == 0) {                          /* flush twice */
      res = arc_nft2_stream_flush(st);
      walk(res);
      if (res) arc_result_free(res);
    }
  }
  arc_nft2_stream_close(st);
}

static void fuzz_one(src_t* r) {
  int ops = 1 + (int)rn(r, 6);
  for (int i = 0; i < ops && !done(r); i++) {
    switch (rn(r, 6)) {
      case 0: op_names(r); break;
      case 1: op_context(r); break;
      case 2: case 3: op_transcribe(r); break;
      default: op_stream(r); break;
    }
  }
}

static int load(const char* dir, const char* ort) {
  char err[1024] = {0};
  if (arc_ort_set_library(ort) != 0) { fprintf(stderr, "ONNX Runtime: %s\n", arc_ort_error()); return -1; }
  M = arc_nft2_create(dir, 2, err, sizeof err);
  if (!M) { fprintf(stderr, "arc_nft2_create: %s\n", err); return -1; }
  RAW = getenv("ARC_FUZZ_RAW") && getenv("ARC_FUZZ_RAW")[0] == '1';
  fprintf(stderr, "libarc %s (ABI %d), backend %s\n", arc_version(), arc_abi_version(), arc_nft2_backend());
  return 0;
}

#ifdef ARC_LIBFUZZER
int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
  if (!M && load(getenv("ARC_NFT2_DIR"), getenv("ARC_ORT_LIB")) != 0) abort();
  src_t r = {data, size, 0, 0};
  fuzz_one(&r);
  return 0;
}
#else
static double now_s(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}

int main(int argc, char** argv) {
  if (argc < 3) { fprintf(stderr, "usage: %s <nft2 dir> <libonnxruntime> [seconds=120] [seed]\n", argv[0]); return 2; }
  double secs = argc > 3 ? atof(argv[3]) : 120.0;
  uint64_t seed = argc > 4 ? strtoull(argv[4], NULL, 10) : (uint64_t)time(NULL) * 2654435761u;
  if (!seed) seed = 1;
  if (load(argv[1], argv[2]) != 0) return 3;
  fprintf(stderr, "seed %llu, %.0f s\n", (unsigned long long)seed, secs);
  double t0 = now_s();
  long iters = 0;
  while (now_s() - t0 < secs) {
    /* one case = one sub-seed, so a crash is replayable: fuzz_libarc dir ort 1 <case seed> runs it first */
    uint64_t cs = seed + (uint64_t)iters * 0x9E3779B97F4A7C15ull;
    if (!cs) cs = 1;
    fprintf(stderr, "case %ld seed %llu\n", iters, (unsigned long long)cs);
    src_t r = {NULL, 0, 0, cs};
    fuzz_one(&r);
    iters++;
  }
  arc_nft2_destroy(M);
  printf("{\"cases\": %ld, \"calls\": %ld, \"results\": %ld, \"null_results\": %ld, \"seconds\": %.1f, \"seed\": %llu}\n",
         iters, N_CALLS, N_RESULTS, N_NULL, now_s() - t0, (unsigned long long)seed);
  return 0;
}
#endif
