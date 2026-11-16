/* libarc in-process, from the static library (issue #93, docs/EMBEDDING.md): load the ear (Arc Transcriber Space,
 * the nft2/ folder) with the pinned ONNX Runtime, transcribe one 16 kHz mono PCM16 clip, print JSON.
 *
 *   cmake -S desktop/vendor/libarc -B build -DARC_BUILD_STATIC=ON -DARC_BUILD_EXAMPLES=ON && cmake --build build
 *   build/transcribe <nft2 dir> <libonnxruntime> <clip.wav | clip.s16le> [--names "Shackleton:lunar_feature;..."]
 *                    [--threads 4] [--domain assistant]
 *
 * The output's utts / names / numbers / events have the same fields and rounding as the model server's
 * Nft2.transcribe (model_server/app/nft2.py), so the two can be compared directly. Exit 0 ok, 1 usage / load / decode
 * error (the message on stderr and as {"error": ...} on stdout). */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "arc.h"

static double now_s(void) {
  struct timespec t;
  timespec_get(&t, TIME_UTC);
  return (double)t.tv_sec + t.tv_nsec / 1e9;
}

/* ---- JSON output ---- */
static void jstr(const char* s) {
  if (!s) {
    fputs("null", stdout);
    return;
  }
  putchar('"');
  for (const unsigned char* p = (const unsigned char*)s; *p; ++p) {
    if (*p == '"' || *p == '\\') printf("\\%c", *p);
    else if (*p == '\n') fputs("\\n", stdout);
    else if (*p == '\t') fputs("\\t", stdout);
    else if (*p < 0x20) printf("\\u%04x", *p);
    else putchar(*p);
  }
  putchar('"');
}
/* Python's round(x, nd) for display; < 0 (not available) -> null, as nft2.py's _f */
static void jnum(double x, int nd, int neg_is_null) {
  if (neg_is_null && x < 0) fputs("null", stdout);
  else if (!isfinite(x)) fputs("null", stdout);
  else printf("%.*f", nd, x);
}

static void words(const arc_word* w, int n) {
  putchar('[');
  for (int k = 0; k < n; ++k) {
    printf(k ? ", {\"w\": " : "{\"w\": ");
    jstr(w[k].text);
    printf(", \"t0\": %.3f, \"t1\": %.3f", w[k].start, w[k].end);
    if (w[k].tag) {
      fputs(", \"tag\": ", stdout);
      jstr(w[k].tag);
      printf(", \"tag_begin\": %s", w[k].tag_begin ? "true" : "false");
    }
    putchar('}');
  }
  putchar(']');
}

static void print_result(const arc_result* r, double load_s, double ms) {
  printf("{\"backend\": ");
  jstr(arc_nft2_backend());
  printf(", \"libarc\": ");
  jstr(arc_version());
  printf(", \"abi\": %d, \"load_s\": %.2f, \"ms\": %.1f, \"audio_s\": %.3f,\n \"utts\": [", arc_abi_version(), load_s,
         ms, r->audio_s);
  for (int i = 0; i < r->n_utts; ++i) {
    const arc_utt* u = &r->utts[i];
    printf(i ? ",\n  {" : "\n  {");
    printf("\"t0\": %.3f, \"t1\": %.3f, \"text\": ", u->start, u->end);
    jstr(u->text ? u->text : "");
    fputs(", \"decoder_text\": ", stdout);
    jstr(u->decoder_text);
    fputs(", \"tags\": [", stdout);
    for (int k = 0; k < u->n_tags; ++k) {
      printf(k ? ", {\"tag\": " : "{\"tag\": ");
      jstr(u->tags[k].tag);
      printf(", \"b\": %d, \"e\": %d, \"text\": ", u->tags[k].word_begin, u->tags[k].word_end);
      jstr(u->tags[k].text);
      putchar('}');
    }
    fputs("], \"words\": ", stdout);
    words(u->words, u->n_words);
    fputs(", \"device_directed\": ", stdout);
    jnum(u->device_directed, 3, 1);
    fputs(", \"directed\": ", stdout);
    fputs(u->directed < 0 ? "null" : u->directed ? "true" : "false", stdout);
    fputs(", \"intent\": ", stdout);
    if (u->intent.label) {
      fputs("{\"label\": ", stdout);
      jstr(u->intent.label);
      fputs(", \"p\": ", stdout);
      jnum(u->intent.p, 3, 1);
      putchar('}');
    } else {
      fputs("null", stdout);
    }
    putchar('}');
  }
  fputs("],\n \"names\": [", stdout);
  for (int i = 0; i < r->n_names; ++i) {
    const arc_name* n = &r->names[i];
    printf(i ? ", {\"t0\": %.3f, \"t1\": %.3f, \"tag\": " : "{\"t0\": %.3f, \"t1\": %.3f, \"tag\": ", n->start, n->end);
    jstr(n->tag);
    fputs(", \"heard\": ", stdout);
    jstr(n->heard);
    fputs(", \"entity\": ", stdout);
    jstr(n->entity);
    printf(", \"kb_index\": %d, \"state\": ", n->kb_index);
    jstr(n->state);
    fputs(", \"p\": ", stdout);
    jnum(n->p, 3, 1);
    putchar('}');
  }
  fputs("],\n \"numbers\": [", stdout);
  for (int i = 0; i < r->n_numbers; ++i) {
    const arc_number* n = &r->numbers[i];
    printf(i ? ", {\"t0\": %.3f, \"t1\": %.3f, \"kind\": " : "{\"t0\": %.3f, \"t1\": %.3f, \"kind\": ", n->start, n->end);
    jstr(n->kind);
    fputs(", \"unit\": ", stdout);
    jstr(n->unit);
    fputs(", \"heard\": ", stdout);
    jstr(n->heard);
    fputs(", \"value\": ", stdout);
    if (n->has_value) printf("%.17g", n->value);
    else fputs("null", stdout);
    fputs(", \"state\": ", stdout);
    jstr(n->state);
    putchar('}');
  }
  fputs("],\n \"events\": [", stdout);
  for (int i = 0; i < r->n_events; ++i) {
    const arc_event* e = &r->events[i];
    printf(i ? ", {\"label\": " : "{\"label\": ");
    jstr(e->label);
    printf(", \"t0\": %.3f, \"t1\": %.3f, \"p\": %.4f}", e->start, e->end, e->p);
  }
  fputs("]}\n", stdout);
}

static int fail(const char* what, const char* why) {
  fprintf(stderr, "transcribe: %s: %s\n", what, why ? why : "");
  printf("{\"error\": ");
  jstr(what);
  printf(", \"reason\": ");
  jstr(why);
  puts("}");
  return 1;
}

/* ---- audio: a 16 kHz mono PCM16 WAV (RIFF chunks walked, so LIST / fact chunks are fine) or raw s16le ---- */
static uint32_t le32(const unsigned char* p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }
static uint16_t le16(const unsigned char* p) { return (uint16_t)(p[0] | p[1] << 8); }

static float* read_pcm(const char* path, size_t* n, char* why, size_t why_len) {
  FILE* f = fopen(path, "rb");
  if (!f) {
    snprintf(why, why_len, "cannot open %s", path);
    return NULL;
  }
  fseek(f, 0, SEEK_END);
  long len = ftell(f);
  fseek(f, 0, SEEK_SET);
  unsigned char* b = len > 0 ? malloc((size_t)len) : NULL;
  if (!b || fread(b, 1, (size_t)len, f) != (size_t)len) {
    fclose(f);
    free(b);
    snprintf(why, why_len, "cannot read %s", path);
    return NULL;
  }
  fclose(f);
  const unsigned char* pcm = b;
  size_t bytes = (size_t)len;
  if (len >= 12 && !memcmp(b, "RIFF", 4) && !memcmp(b + 8, "WAVE", 4)) {
    pcm = NULL;
    int fmt_ok = 0;
    for (size_t o = 12; o + 8 <= (size_t)len;) {
      uint32_t sz = le32(b + o + 4);
      const unsigned char* d = b + o + 8;
      if (sz > (size_t)len - o - 8) sz = (uint32_t)((size_t)len - o - 8);
      if (!memcmp(b + o, "fmt ", 4) && sz >= 16) {
        fmt_ok = le16(d) == 1 && le16(d + 2) == 1 && le32(d + 4) == ARC_SAMPLE_RATE && le16(d + 14) == 16;
        if (!fmt_ok) {
          snprintf(why, why_len, "%s: need 16 kHz mono PCM16 (format %u, %u ch, %u Hz, %u bit)", path, le16(d),
                   le16(d + 2), le32(d + 4), le16(d + 14));
          free(b);
          return NULL;
        }
      } else if (!memcmp(b + o, "data", 4)) {
        pcm = d;
        bytes = sz;
        break;
      }
      o += 8 + sz + (sz & 1);
    }
    if (!pcm || !fmt_ok) {
      snprintf(why, why_len, "%s: no fmt / data chunk", path);
      free(b);
      return NULL;
    }
  }
  *n = bytes / 2;
  float* x = malloc(sizeof(float) * (*n ? *n : 1));
  for (size_t i = 0; i < *n; ++i) x[i] = (float)(int16_t)le16(pcm + 2 * i) / 32768.0f;   /* as the model server */
  free(b);
  return x;
}

/* "Name:kind;Other Name:kind" (kind optional) */
static int parse_names(char* spec, arc_name_entry* out, int cap) {
  int n = 0;
  for (char* tok = strtok(spec, ";"); tok && n < cap; tok = strtok(NULL, ";")) {
    char* colon = strrchr(tok, ':');
    if (colon) *colon = 0;
    if (!*tok) continue;
    out[n++] = (arc_name_entry){tok, colon && colon[1] ? colon + 1 : NULL, NULL, NULL, 0};
  }
  return n;
}

int main(int argc, char** argv) {
  if (argc < 4) {
    fprintf(stderr, "usage: %s <nft2 dir> <libonnxruntime> <clip.wav|clip.s16le> [--names \"Name:kind;...\"] "
                    "[--threads N] [--domain assistant]\n", argv[0]);
    return 1;
  }
  const char *dir = argv[1], *ort = argv[2], *clip = argv[3], *domain = "assistant";
  char* names_spec = NULL;
  int threads = 4;
  for (int i = 4; i + 1 < argc; i += 2) {
    if (!strcmp(argv[i], "--names")) names_spec = argv[i + 1];
    else if (!strcmp(argv[i], "--threads")) threads = atoi(argv[i + 1]);
    else if (!strcmp(argv[i], "--domain")) domain = argv[i + 1];
    else return fail("unknown option", argv[i]);
  }
  if (arc_abi_version() != ARC_ABI_VERSION) return fail("libarc ABI", "the library and arc.h differ");

  char why[1024];
  size_t n = 0;
  float* pcm = read_pcm(clip, &n, why, sizeof why);
  if (!pcm) return fail("audio", why);

  /* The pinned runtime by path (desktop/vendor/libarc/onnxruntime.lock.json). The sha256 check the model server does
   * at load (nft2.resolve_ort) is the embedder's job: see docs/EMBEDDING.md. */
  if (arc_ort_set_library(ort) != 0) return fail("onnxruntime", arc_ort_error());
  double t = now_s();
  arc_nft2* m = arc_nft2_create(dir, threads, why, sizeof why);
  if (!m) return fail("arc_nft2_create", why);
  double load_s = now_s() - t;

  arc_name_entry kb[64];
  int n_kb = names_spec ? parse_names(names_spec, kb, 64) : 0;
  if (n_kb && arc_nft2_set_names(m, kb, n_kb) != 0) return fail("arc_nft2_set_names", arc_last_error());

  arc_nft2_options o = {domain, 0, 0};
  t = now_s();
  arc_result* r = arc_nft2_transcribe(m, pcm, n, &o);   /* one model, one call at a time: this is the only caller */
  double ms = (now_s() - t) * 1000;
  if (!r) return fail("arc_nft2_transcribe", arc_last_error());
  print_result(r, load_s, ms);
  arc_result_free(r);
  arc_nft2_destroy(m);
  free(pcm);
  return 0;
}
