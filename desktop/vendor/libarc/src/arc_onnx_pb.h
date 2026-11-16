/* A few lines of protobuf for ONNX ModelProto / GraphProto, no protobuf library: shared by the ONNX Runtime backend
 * (arc_nft2_ort.c) and the browser backend (arc_nft2_web.c), which both add the Arc tap as an extra graph output.
 * Moved out of arc_nft2_ort.c unchanged (issue #93). Part of arc_transcriber (Whissle Inc.), CC BY-NC 4.0; see LICENSE. */
#ifndef ARC_ONNX_PB_H
#define ARC_ONNX_PB_H

#include <stddef.h>
#include <stdint.h>

/* an initializer stored in encoder.weights: its name, ONNX element type, dims and place in the file */
typedef struct {
  char* name;
  int dtype, ndim;
  int64_t dims[8];
  uint64_t offset, length;
} arc_onnx_ext;

/* model bytes -> the same model with `extra_out` appended to the graph outputs (NULL: unchanged; *out malloc'd) and
 * the graph's initializers stored in encoder.weights (*ext calloc'd, each name malloc'd). 0, or -1 (arc_seterr). */
int arc_onnx_edit_model(const uint8_t* p, size_t n, const char* extra_out, uint8_t** out, size_t* out_n,
                        arc_onnx_ext** ext, int* n_ext);

#endif
