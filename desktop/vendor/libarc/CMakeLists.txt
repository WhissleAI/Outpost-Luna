# libarc as one shared library for the Outpost Luna ear (Arc Transcriber Space, model_server/app/nft2.py):
#   macOS libarc.dylib, Windows arc.dll (clang / clang-cl) or libarc.dll (mingw-w64), Linux libarc.so.
# Needs a GCC/Clang-compatible compiler (C11 atomics, __builtin_popcountll, target attributes): not plain cl.exe.
# ONNX Runtime is NOT linked: ort_loader.c loads it by path at run time (see NOTICE), so only its 1.23.2 C API headers
# (third_party/onnxruntime/include, C API 23) are needed to compile. The runtime itself is pinned in
# onnxruntime.lock.json: configuring downloads that exact build (sha256-checked) into <build>/onnxruntime/, which the
# build scripts copy next to libarc (cmake/vendor_onnxruntime.cmake).
#   cmake -S desktop/vendor/libarc -B desktop/build/libarc -DCMAKE_BUILD_TYPE=Release && cmake --build desktop/build/libarc
# CMake 3.21+ (string(JSON), file(ARCHIVE_EXTRACT ... PATTERNS), file(COPY_FILE)).
cmake_minimum_required(VERSION 3.21)
project(arc C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release)
endif()

# In-process embedding (issue #93, docs/EMBEDDING.md): the same C API (include/arc.h) as a static library too.
#   -DARC_BUILD_STATIC=ON   also build <build>/static/libarc.a (arc.lib with clang-cl; libarc.a with mingw) next to the
#                           shared library, whose build and outputs do not change. Kept in static/ so the shared
#                           library's import lib (arc.lib) and `cp <build>/libarc.*` in the desktop scripts never see it.
#   -DARC_ORT_LINKED=ON     ONNX Runtime is linked by the embedder (a static ORT, or ORT's WebAssembly static lib)
#                           instead of loaded at run time: ort_linked.c replaces ort_loader.c, arc_ort_set_library()
#                           is accepted and ignored. Default OFF: the run-time loader (pinned ORT by path), as today.
#   -DARC_NFT2_BACKEND=web  Emscripten only: the encoder / RNNT nets run on onnxruntime-web from JavaScript
#                           (src/arc_nft2_web.c, wasm/), see docs/EMBEDDING.md "WebAssembly".
#   -DARC_BUILD_EXAMPLES=ON examples/transcribe (linked against the static library; needs ARC_BUILD_STATIC).
# An Emscripten configure (emcmake cmake ..., or -DCMAKE_TOOLCHAIN_FILE=cmake/emscripten.cmake) builds the static
# library only, single-threaded (libarc's pool runs serially when no thread can start), with no ORT download.
option(ARC_BUILD_STATIC "Also build libarc as a static library (<build>/static/)" OFF)
option(ARC_ORT_LINKED "ONNX Runtime linked by the embedder, not loaded at run time" OFF)
option(ARC_BUILD_EXAMPLES "Build examples/ against the static library" OFF)
set(ARC_NFT2_BACKEND "ort" CACHE STRING "NFT2 encoder / RNNT backend: ort, web (Emscripten + onnxruntime-web), none")
set_property(CACHE ARC_NFT2_BACKEND PROPERTY STRINGS ort web none)

file(GLOB ARC_SRC ${CMAKE_CURRENT_SOURCE_DIR}/src/*.c)
list(FILTER ARC_SRC EXCLUDE REGEX "arc_nft2_(none|ort|web)\\.c$")
if(ARC_NFT2_BACKEND STREQUAL "ort")
  if(EMSCRIPTEN AND NOT ARC_ORT_LINKED)
    # nothing to load at run time in a browser: link ORT's own WebAssembly static library (docs/EMBEDDING.md, path A)
    message(FATAL_ERROR "Emscripten + ARC_NFT2_BACKEND=ort needs -DARC_ORT_LINKED=ON and libonnxruntime_webassembly.a")
  endif()
  list(APPEND ARC_SRC ${CMAKE_CURRENT_SOURCE_DIR}/src/arc_nft2_ort.c)
  if(ARC_ORT_LINKED)
    list(APPEND ARC_SRC ${CMAKE_CURRENT_SOURCE_DIR}/ort_linked.c)
  else()
    list(APPEND ARC_SRC ${CMAKE_CURRENT_SOURCE_DIR}/ort_loader.c)
  endif()
elseif(ARC_NFT2_BACKEND STREQUAL "web")
  if(NOT EMSCRIPTEN)
    message(FATAL_ERROR "ARC_NFT2_BACKEND=web needs Emscripten (emcmake cmake ...)")
  endif()
  list(APPEND ARC_SRC ${CMAKE_CURRENT_SOURCE_DIR}/src/arc_nft2_web.c ${CMAKE_CURRENT_SOURCE_DIR}/ort_linked.c)
elseif(ARC_NFT2_BACKEND STREQUAL "none")
  list(APPEND ARC_SRC ${CMAKE_CURRENT_SOURCE_DIR}/src/arc_nft2_none.c ${CMAKE_CURRENT_SOURCE_DIR}/ort_linked.c)
else()
  message(FATAL_ERROR "ARC_NFT2_BACKEND must be ort, web or none (got '${ARC_NFT2_BACKEND}')")
endif()

if(CMAKE_C_COMPILER_ID STREQUAL "MSVC")
  message(FATAL_ERROR "libarc needs clang (LLVM clang + Ninja, or Visual Studio -T ClangCL) or mingw-w64, not cl.exe")
endif()

# Everything both library kinds share. vis: PRIVATE for the shared library (its dependencies stay inside it), PUBLIC
# for the static one (whoever links libarc.a also needs threads, libm, libdl, psapi).
function(arc_configure tgt vis)
  target_include_directories(${tgt} PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
  target_include_directories(${tgt} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
                                            ${CMAKE_CURRENT_SOURCE_DIR}/third_party/onnxruntime/include)
  if(ARC_NFT2_BACKEND STREQUAL "ort")
    target_compile_definitions(${tgt} PRIVATE ARC_HAVE_ORT)
  endif()
  if(WIN32)
    target_include_directories(${tgt} BEFORE PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/compat/win)
    target_compile_definitions(${tgt} PRIVATE WIN32_LEAN_AND_MEAN _CRT_SECURE_NO_WARNINGS)
    # UTF-8 paths for fopen / open / rename / remove (a user name with non-ASCII letters): compat/win/arc_u8io.h
    target_sources(${tgt} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/compat/win/arc_u8io.c)
    if(MSVC)
      target_compile_options(${tgt} PRIVATE "/FI${CMAKE_CURRENT_SOURCE_DIR}/compat/win/arc_u8io.h")
    else()
      target_compile_options(${tgt} PRIVATE -include "${CMAKE_CURRENT_SOURCE_DIR}/compat/win/arc_u8io.h")
    endif()
    target_link_libraries(${tgt} ${vis} psapi)
  elseif(EMSCRIPTEN)
    target_link_libraries(${tgt} ${vis} m)
  else()
    find_package(Threads REQUIRED)
    target_link_libraries(${tgt} ${vis} Threads::Threads m ${CMAKE_DL_LIBS})
  endif()
  if(MSVC)
    # clang-cl (Visual Studio -T ClangCL): the AVX2/FMA kernels need /arch:AVX2 here (found by a Windows tester,
    # 2026-11-15). Windows builds therefore need an AVX2 CPU (Intel 2013+ / AMD 2015+). The clang + Ninja path below is unchanged.
    target_compile_options(${tgt} PRIVATE /O2 /W3 /arch:AVX2)
  else()
    target_compile_options(${tgt} PRIVATE -O2 -Wall -Wno-unused-parameter -Wno-unused-function -Wno-unused-but-set-variable)
  endif()
  if(EMSCRIPTEN)
    target_compile_options(${tgt} PRIVATE -msimd128)
  endif()
endfunction()

if(NOT EMSCRIPTEN)
  add_library(arc SHARED ${ARC_SRC})
  arc_configure(arc PRIVATE)
  if(WIN32)
    set_target_properties(arc PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS ON)
    if(MINGW)
      # one self-contained DLL: no libgcc / libwinpthread DLLs next to it (desktop/scripts/win_bundle_check.py dlls)
      target_link_options(arc PRIVATE -static -static-libgcc -Wl,--export-all-symbols)
    endif()
  endif()
endif()

if(ARC_BUILD_STATIC OR EMSCRIPTEN)
  add_library(arc_static STATIC ${ARC_SRC})
  arc_configure(arc_static PUBLIC)
  set_target_properties(arc_static PROPERTIES OUTPUT_NAME arc
                        ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/static
                        ARCHIVE_OUTPUT_DIRECTORY_RELEASE ${CMAKE_BINARY_DIR}/static
                        ARCHIVE_OUTPUT_DIRECTORY_DEBUG ${CMAKE_BINARY_DIR}/static/Debug)
  add_library(arc::static ALIAS arc_static)
endif()

if(ARC_BUILD_EXAMPLES)
  if(NOT TARGET arc_static)
    message(FATAL_ERROR "ARC_BUILD_EXAMPLES needs ARC_BUILD_STATIC=ON")
  endif()
  if(NOT EMSCRIPTEN)
    add_executable(arc_transcribe ${CMAKE_CURRENT_SOURCE_DIR}/examples/transcribe.c)
    target_link_libraries(arc_transcribe PRIVATE arc_static)
    set_target_properties(arc_transcribe PROPERTIES OUTPUT_NAME transcribe)
  endif()
endif()

if(EMSCRIPTEN)
  # wasm/arc.mjs + arc.wasm: examples/transcribe.c as an ES module the page runs with callMain (wasm/index.html).
  # Asyncify suspends the C stack while onnxruntime-web runs a graph (arc_nft2_web.c). No ONNX Runtime download.
  if(ARC_NFT2_BACKEND STREQUAL "web")
    add_executable(arc_web ${CMAKE_CURRENT_SOURCE_DIR}/examples/transcribe.c)
    target_link_libraries(arc_web PRIVATE arc_static)
    set_target_properties(arc_web PROPERTIES OUTPUT_NAME arc SUFFIX ".mjs")
    target_link_options(arc_web PRIVATE -O2 -sASYNCIFY=1 -sASYNCIFY_STACK_SIZE=1048576 -sSTACK_SIZE=8388608
      -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=268435456 -sMAXIMUM_MEMORY=4294967296 -sINVOKE_RUN=0
      -sEXIT_RUNTIME=0 -sMODULARIZE=1 -sEXPORT_ES6=1 -sEXPORT_NAME=createArc -sENVIRONMENT=web,worker
      -sFORCE_FILESYSTEM=1 "-sEXPORTED_RUNTIME_METHODS=['FS','callMain','HEAPU8']")
  endif()
  return()
endif()
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/vendor_onnxruntime.cmake)
arc_vendor_onnxruntime()
