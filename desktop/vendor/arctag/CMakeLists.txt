# Arc Tagger C library, native backend only (no ONNX Runtime), as one shared library for the model server's ctypes binding:
# libarctag.dylib (macOS), libarctag.so (Linux), arctag.dll (Windows).
# Sources: WhissleAI/arc-tagger-c 0.5.0 (main 4318e4a, PR #10: kids domain + guard layer, src/guard.c), CC BY-NC 4.0, see LICENSE.
# Local patches: u8file.h (UTF-8 model paths on Windows: u8_fopen in arctag.c, tokenizer.c, onnx_file.c) and the "gold" -> "human"
# asr-source alias in arctag.c.
#   cmake -S desktop/vendor/arctag -B desktop/build/arctag -DCMAKE_BUILD_TYPE=Release && cmake --build desktop/build/arctag --config Release
cmake_minimum_required(VERSION 3.16)
project(arctag_desktop LANGUAGES C)
set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release)
endif()

add_library(arctag SHARED src/arctag.c src/guard.c src/native.c src/onnx_file.c src/tokenizer.c third_party/cjson/cJSON.c)
target_compile_definitions(arctag PRIVATE ARCTAG_BUILD_SHARED)   # __declspec(dllexport) on Windows
target_include_directories(arctag PUBLIC include PRIVATE src third_party/cjson)
if(APPLE)
  target_link_libraries(arctag PRIVATE "-framework Accelerate")
  set_target_properties(arctag PROPERTIES INSTALL_NAME_DIR "@rpath" BUILD_WITH_INSTALL_NAME_DIR ON)
endif()
if(NOT WIN32)
  target_link_libraries(arctag PRIVATE m)
  target_compile_options(arctag PRIVATE -O3 -Wall -Wno-unused-function)
endif()
if(MINGW)
  # mingw-w64 (desktop/scripts/cross-build-windows.sh from a Mac, or MSYS2): gcc, so native.c takes its AVX2 + FMA kernels
  # (checked against the CPU at load). Static libgcc / winpthread, so arctag.dll needs only Windows' own DLLs, and no
  # "lib" prefix, so the file is arctag.dll as the app expects.
  target_compile_options(arctag PRIVATE -O3 -Wall -Wno-unused-function)
  target_link_options(arctag PRIVATE -static-libgcc -static)
  set_target_properties(arctag PROPERTIES PREFIX "")
endif()
if(MSVC)
  # MSVC has no __x86_64__, so native.c falls back to its portable scalar kernels (correct, slower than AVX2).
  # Building with clang-cl (-T ClangCL) gets the AVX2 kernels. Untested on Windows.
  target_compile_definitions(arctag PRIVATE _CRT_SECURE_NO_WARNINGS)
  target_compile_options(arctag PRIVATE /O2)
  set_target_properties(arctag PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS OFF)
endif()
