/* Outpost Luna: ONNX Runtime resolved at run time (see NOTICE). libarc's ONNX backend calls OrtGetApiBase(); this file
 * defines it by loading the runtime library named by arc_ort_set_library() or the ARC_ORT_LIB environment variable.
 * When nothing can be loaded, a stub base answers GetApi() with NULL, and arc_nft2_create fails with a message
 * ("onnxruntime: API version 23 not available (library <reason>)") instead of crashing. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "onnxruntime_c_api.h"

#ifdef _WIN32
#include <windows.h>
#define ARC_EXPORT /* every symbol is exported: CMake WINDOWS_EXPORT_ALL_SYMBOLS (MSVC), --export-all-symbols (mingw) */
#else
#include <dlfcn.h>
#include <pthread.h>
#define ARC_EXPORT __attribute__((visibility("default")))
#endif

typedef const OrtApiBase*(ORT_API_CALL* get_base_fn)(void);

static char g_path[4096];
static char g_why[600] = "not loaded: call arc_ort_set_library() or set ARC_ORT_LIB";
static const OrtApiBase* g_base;

static const OrtApi* ORT_API_CALL stub_get_api(uint32_t v) {
  (void)v;
  return NULL;
}
static const char* ORT_API_CALL stub_version(void) { return g_why; }
static const OrtApiBase g_stub = {stub_get_api, stub_version};

static const OrtApiBase* load(void) {
  const char* p = g_path[0] ? g_path : getenv("ARC_ORT_LIB");
  if (!p || !*p) return NULL;
  get_base_fn fn = NULL;
#ifdef _WIN32
  wchar_t w[4096];
  if (!MultiByteToWideChar(CP_UTF8, 0, p, -1, w, 4096)) {
    snprintf(g_why, sizeof g_why, "bad path %s", p);
    return NULL;
  }
  HMODULE h = LoadLibraryExW(w, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
  if (!h) {
    snprintf(g_why, sizeof g_why, "cannot load %s (error %lu)", p, (unsigned long)GetLastError());
    return NULL;
  }
  fn = (get_base_fn)(void*)GetProcAddress(h, "OrtGetApiBase");
#else
  void* h = dlopen(p, RTLD_NOW | RTLD_LOCAL);
  if (!h) {
    snprintf(g_why, sizeof g_why, "cannot load %s: %s", p, dlerror());
    return NULL;
  }
  fn = (get_base_fn)dlsym(h, "OrtGetApiBase");
#endif
  if (!fn) {
    snprintf(g_why, sizeof g_why, "%s has no OrtGetApiBase", p);
    return NULL;
  }
  return fn();
}

/* The ONNX Runtime library to use (a full path). 0 when it loaded and serves API version 23, else -1 (the reason in
 * arc_ort_error()). Call before arc_nft2_create; later calls after a successful load are ignored. */
ARC_EXPORT int arc_ort_set_library(const char* path) {
  if (g_base) return 0;
  snprintf(g_path, sizeof g_path, "%s", path ? path : "");
  g_base = load();
  if (g_base && !g_base->GetApi(ORT_API_VERSION)) {
    snprintf(g_why, sizeof g_why, "%s (onnxruntime %s) does not serve C API version %d", g_path,
             g_base->GetVersionString(), ORT_API_VERSION);
    g_base = NULL;
  }
  return g_base ? 0 : -1;
}

ARC_EXPORT const char* arc_ort_error(void) { return g_base ? "" : g_why; }

const OrtApiBase* ORT_API_CALL OrtGetApiBase(void) NO_EXCEPTION {
  if (!g_base) g_base = load();
  return g_base ? g_base : &g_stub;
}
