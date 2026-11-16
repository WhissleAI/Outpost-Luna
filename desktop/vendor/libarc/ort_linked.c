/* Outpost Luna: ONNX Runtime LINKED by the embedder (CMake -DARC_ORT_LINKED=ON, and the web / none backends), the
 * counterpart of ort_loader.c. OrtGetApiBase comes from the ONNX Runtime the program links (a static ORT, ORT's
 * WebAssembly static library libonnxruntime_webassembly.a), or is not needed at all (ARC_NFT2_BACKEND=web / none).
 * arc_ort_set_library() is accepted and ignored so code written for the loader runs unchanged. docs/EMBEDDING.md. */
#include "arc.h"

int arc_ort_set_library(const char* path) {
  (void)path;
  return 0;
}

const char* arc_ort_error(void) { return ""; }
