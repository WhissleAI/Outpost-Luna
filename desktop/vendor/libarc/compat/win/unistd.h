/* Outpost Luna Windows shim: open / close / read for MSVC (mingw-w64 has its own; this one is equivalent). */
#ifndef ARC_COMPAT_UNISTD_H
#define ARC_COMPAT_UNISTD_H
#include <io.h>
#include <fcntl.h>
#ifdef _MSC_VER
#define open _open
#define close _close
#define O_RDONLY _O_RDONLY
#endif
#endif
