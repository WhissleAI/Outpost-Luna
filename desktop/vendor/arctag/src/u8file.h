/* fopen with a UTF-8 path on every OS. The model path arrives as UTF-8 (the Python binding encodes it). Windows' fopen
 * reads a path in the ANSI code page, so a model under a user folder with an accent in its name would not
 * open there: convert to UTF-16 and use _wfopen. Elsewhere this is plain fopen. */
#ifndef ARCTAG_U8FILE_H
#define ARCTAG_U8FILE_H
#include <stdio.h>
#ifdef _WIN32
#include <stdlib.h>
#include <wchar.h>
#include <windows.h>
static inline FILE *u8_fopen(const char *path, const char *mode) {
    wchar_t wm[8];
    int i = 0;
    for (; mode[i] && i < 7; i++) wm[i] = (wchar_t)mode[i];
    wm[i] = 0;
    int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, NULL, 0);
    if (n <= 0) return fopen(path, mode);              /* not valid UTF-8: let the C runtime try it as given */
    wchar_t *wp = (wchar_t *)malloc(sizeof(wchar_t) * (size_t)n);
    if (!wp) return NULL;
    MultiByteToWideChar(CP_UTF8, 0, path, -1, wp, n);
    FILE *f = _wfopen(wp, wm);
    free(wp);
    return f;
}
#else
#define u8_fopen fopen
#endif
#endif
