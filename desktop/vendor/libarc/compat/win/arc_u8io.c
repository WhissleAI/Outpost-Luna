/* Outpost Luna Windows shim: UTF-8 file paths (see arc_u8io.h). */
#define ARC_U8IO_IMPL
#include "arc_u8io.h"

#include <stdlib.h>
#include <windows.h>

static wchar_t* wide(const char* s) {
  int n = s ? MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, NULL, 0) : 0;
  if (n <= 0) return NULL;
  wchar_t* w = (wchar_t*)malloc(sizeof(wchar_t) * (size_t)n);
  if (w && MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, w, n) <= 0) {
    free(w);
    w = NULL;
  }
  return w;
}

FILE* arc_u8_fopen(const char* path, const char* mode) {
  wchar_t *wp = wide(path), *wm = wide(mode);
  FILE* f = (wp && wm) ? _wfopen(wp, wm) : fopen(path, mode);
  free(wp);
  free(wm);
  return f;
}

int arc_u8_open(const char* path, int flags, ...) {
  wchar_t* wp = wide(path);
  int fd = wp ? _wopen(wp, flags | _O_BINARY) : _open(path, flags | _O_BINARY);
  free(wp);
  return fd;
}

int arc_u8_rename(const char* from, const char* to) {
  wchar_t *a = wide(from), *b = wide(to);
  int r = (a && b) ? (MoveFileExW(a, b, MOVEFILE_REPLACE_EXISTING) ? 0 : -1) : rename(from, to);
  free(a);
  free(b);
  return r;
}

int arc_u8_remove(const char* path) {
  wchar_t* wp = wide(path);
  int r = wp ? _wremove(wp) : remove(path);
  free(wp);
  return r;
}
