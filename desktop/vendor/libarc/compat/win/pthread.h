/* Outpost Luna Windows shim: the one pthread feature src/arc_nft2_ort.c uses (a static mutex), on an SRWLOCK. */
#ifndef ARC_COMPAT_PTHREAD_H
#define ARC_COMPAT_PTHREAD_H
#include <windows.h>
typedef SRWLOCK pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER SRWLOCK_INIT
static __inline int pthread_mutex_lock(pthread_mutex_t* m) { AcquireSRWLockExclusive(m); return 0; }
static __inline int pthread_mutex_unlock(pthread_mutex_t* m) { ReleaseSRWLockExclusive(m); return 0; }
#endif
