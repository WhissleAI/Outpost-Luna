/* Outpost Luna Windows shim: UTF-8 file paths. Force-included into every libarc source on Windows (CMakeLists.txt);
 * the functions are in arc_u8io.c.
 *
 * The model server passes paths as UTF-8 (model_server/app/nft2.py: str(path).encode()). Windows' fopen / _open read a
 * char* path in the ANSI code page instead, so a model folder under a user name with a non-ASCII letter
 * (C:\Users\Zoë\AppData\Roaming\Outpost Luna\assets\...) would not open, and the ear would not load. These wrappers
 * convert to UTF-16 and call _wfopen / _wopen (always binary: a text-mode fd translates CR LF), and rename replaces an
 * existing file as POSIX rename does. A path that is not valid UTF-8 goes to the C runtime as given.
 * Arc Tagger does the same (desktop/vendor/arctag/src/u8file.h). */
#ifndef ARC_COMPAT_U8IO_H
#define ARC_COMPAT_U8IO_H
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#include <stdio.h>
#include <unistd.h> /* compat/win/unistd.h (MSVC) or mingw's: first, so its own `open` macro is replaced below */

FILE* arc_u8_fopen(const char* path, const char* mode);
int arc_u8_open(const char* path, int flags, ...);
int arc_u8_rename(const char* from, const char* to);
int arc_u8_remove(const char* path);

#ifndef ARC_U8IO_IMPL
#undef open
#define fopen(p, m) arc_u8_fopen((p), (m))
#define open(...) arc_u8_open(__VA_ARGS__)
#define rename(a, b) arc_u8_rename((a), (b))
#define remove(p) arc_u8_remove((p))
#endif
#endif
#endif
