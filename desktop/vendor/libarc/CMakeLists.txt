# libarc as one shared library for the Outpost Luna ear (Arc Transcriber Space, model_server/app/nft2.py):
#   macOS libarc.dylib, Windows arc.dll (clang / clang-cl) or libarc.dll (mingw-w64), Linux libarc.so.
# Needs a GCC/Clang-compatible compiler (C11 atomics, __builtin_popcountll, target attributes): not plain cl.exe.
# ONNX Runtime is NOT linked: ort_loader.c loads the Python onnxruntime wheel's library at run time (see NOTICE), so
# only its 1.23.2 C API headers (third_party/onnxruntime/include) are needed to build.
#   cmake -S desktop/vendor/libarc -B desktop/build/libarc -DCMAKE_BUILD_TYPE=Release && cmake --build desktop/build/libarc
cmake_minimum_required(VERSION 3.16)
project(arc C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release)
endif()

file(GLOB ARC_SRC ${CMAKE_CURRENT_SOURCE_DIR}/src/*.c)
list(FILTER ARC_SRC EXCLUDE REGEX "arc_nft2_none\\.c$")
add_library(arc SHARED ${ARC_SRC} ${CMAKE_CURRENT_SOURCE_DIR}/ort_loader.c)
target_include_directories(arc PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
                                       ${CMAKE_CURRENT_SOURCE_DIR}/third_party/onnxruntime/include)
target_compile_definitions(arc PRIVATE ARC_HAVE_ORT)

if(WIN32)
  target_include_directories(arc BEFORE PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/compat/win)
  target_compile_definitions(arc PRIVATE WIN32_LEAN_AND_MEAN _CRT_SECURE_NO_WARNINGS)
  # UTF-8 paths for fopen / open / rename / remove (a user name with non-ASCII letters): compat/win/arc_u8io.h
  target_sources(arc PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/compat/win/arc_u8io.c)
  if(MSVC)
    target_compile_options(arc PRIVATE "/FI${CMAKE_CURRENT_SOURCE_DIR}/compat/win/arc_u8io.h")
  else()
    target_compile_options(arc PRIVATE -include "${CMAKE_CURRENT_SOURCE_DIR}/compat/win/arc_u8io.h")
  endif()
  set_target_properties(arc PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS ON)
  target_link_libraries(arc PRIVATE psapi)
  if(MINGW)
    # one self-contained DLL: no libgcc / libwinpthread DLLs next to it (desktop/scripts/win_bundle_check.py dlls)
    target_link_options(arc PRIVATE -static -static-libgcc -Wl,--export-all-symbols)
  endif()
else()
  find_package(Threads REQUIRED)
  target_link_libraries(arc PRIVATE Threads::Threads m ${CMAKE_DL_LIBS})
endif()

if(CMAKE_C_COMPILER_ID STREQUAL "MSVC")
  message(FATAL_ERROR "libarc needs clang (LLVM clang + Ninja, or Visual Studio -T ClangCL) or mingw-w64, not cl.exe")
endif()
if(MSVC)
  # clang-cl (Visual Studio -T ClangCL): the AVX2/FMA kernels need /arch:AVX2 here (found by a Windows tester,
  # 2026-11-15). Windows builds therefore need an AVX2 CPU (Intel 2013+ / AMD 2015+). The clang + Ninja path below is unchanged.
  target_compile_options(arc PRIVATE /O2 /W3 /arch:AVX2)
else()
  target_compile_options(arc PRIVATE -O2 -Wall -Wno-unused-parameter -Wno-unused-function -Wno-unused-but-set-variable)
endif()
