/* Outpost Luna Windows shim: read-only mmap / munmap for src/arc_nft2_ort.c (encoder.weights). */
#ifndef ARC_COMPAT_MMAN_H
#define ARC_COMPAT_MMAN_H
#include <io.h>
#include <stddef.h>
#include <windows.h>
#define PROT_READ 1
#define MAP_PRIVATE 2
#define MAP_FAILED ((void*)-1)
static __inline void* mmap(void* addr, size_t len, int prot, int flags, int fd, long long off) {
  (void)addr; (void)prot; (void)flags;
  HANDLE f = (HANDLE)_get_osfhandle(fd);
  if (f == INVALID_HANDLE_VALUE) return MAP_FAILED;
  HANDLE m = CreateFileMappingW(f, NULL, PAGE_READONLY, 0, 0, NULL);
  if (!m) return MAP_FAILED;
  void* p = MapViewOfFile(m, FILE_MAP_READ, (DWORD)((unsigned long long)off >> 32), (DWORD)off, len);
  CloseHandle(m);   /* the view keeps the mapping alive */
  return p ? p : MAP_FAILED;
}
static __inline int munmap(void* p, size_t len) { (void)len; return UnmapViewOfFile(p) ? 0 : -1; }
#endif
