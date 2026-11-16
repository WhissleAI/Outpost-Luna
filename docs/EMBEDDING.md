# Embedding libarc in-process (static library, C API, WebAssembly)

Issue #93. The ear (Arc Transcriber Space on libarc + ONNX Runtime) runs inside the model server today, in a separate
process (docs/LOCAL_EAR.md). Mobile apps and a browser version with no install cannot run a separate process, so they
link libarc into themselves instead. `docs/ENGINE_SERVICE.md` §1 calls this out: "The C API is the shared contract."
This page covers how to do that, the rules of the C API, and where the WebAssembly build stands.

## 1. Static library

```bash
cmake -S desktop/vendor/libarc -B build/libarc -DCMAKE_BUILD_TYPE=Release -DARC_BUILD_STATIC=ON -DARC_BUILD_EXAMPLES=ON
cmake --build build/libarc
#   build/libarc/libarc.dylib            the shared library, unchanged (the desktop app's)
#   build/libarc/static/libarc.a         the static library (arc.lib with clang-cl, libarc.a with mingw-w64)
#   build/libarc/onnxruntime/            the pinned ONNX Runtime (onnxruntime.lock.json), as before
#   build/libarc/transcribe              examples/transcribe.c, linked against static/libarc.a
```

The static library has the **same public C API** (`include/arc.h`, `ARC_ABI_VERSION` 1) built from the same sources
as the shared one. The static archive goes into `static/` so it cannot collide with the shared library's import library
(`arc.lib`) on Windows, and so `cp <build>/libarc.*` in `make desktop-libarc` and the build scripts never picks it up.
`ARC_BUILD_STATIC` is off by default, so `make desktop-libarc`, `build-mac.sh`, `build-windows.ps1`,
`cross-build-windows.sh` and the release gate's ASan build produce exactly what they did before.

| CMake option | Default | Effect |
|---|---|---|
| `ARC_BUILD_STATIC` | OFF | also build `static/libarc.a` (CMake target `arc_static`, alias `arc::static`) |
| `ARC_BUILD_EXAMPLES` | OFF | build `examples/transcribe` against the static library (needs `ARC_BUILD_STATIC`) |
| `ARC_ORT_LINKED` | OFF | the embedder links ONNX Runtime itself; `ort_linked.c` replaces `ort_loader.c`, and `arc_ort_set_library()` returns 0 and does nothing |
| `ARC_NFT2_BACKEND` | `ort` | `ort` (ONNX Runtime C API), `web` (onnxruntime-web, Emscripten only, §4), `none` (no ear) |
| `ARC_ORT_VENDOR` | ON | download the pinned ONNX Runtime next to libarc (unchanged) |

**Linking.** Link `static/libarc.a` plus what it uses:

- Mac and Linux: `-lpthread -lm` (and `-ldl` on Linux).
- Windows: `psapi`.

Through CMake, `target_link_libraries(app PRIVATE arc::static)` brings those in. The compiler must be clang or GCC
(the same rule as the shared build: C11 atomics and GCC builtins, so not `cl.exe`).

**ONNX Runtime stays separate.** By default libarc still loads ONNX Runtime by path at run time (`ort_loader.c`):

1. Call `arc_ort_set_library("<dir>/libonnxruntime.1.32.0.dylib")` before the first `arc_nft2_create`.
2. Ship that pinned file with the app.
3. Check its sha256 against `onnxruntime.lock.json` before loading it, as `model_server/app/nft2.py` does
   (`resolve_ort`). libarc does not check it; that check is the embedder's job.

An app that links ONNX Runtime statically (for example on iOS, where loading a library by path is not allowed) builds
with `-DARC_ORT_LINKED=ON`. The `OrtGetApiBase` symbol then comes from its own ONNX Runtime, which must serve C API 23
or newer (headers in `third_party/onnxruntime/include`).

### The example: `examples/transcribe.c`

```bash
build/libarc/transcribe <nft2 dir> <libonnxruntime> <clip.wav | clip.s16le> [--names "Shackleton:lunar_feature;..."] \
                        [--threads 4] [--domain assistant]
```

The example loads the model and the pinned runtime and transcribes one 16 kHz mono PCM16 clip (a WAV file or raw
s16le). It prints `utts` / `names` / `numbers` / `events` with the same fields and rounding as the model server's
`Nft2.transcribe`. It is about 270 lines with no dependencies beyond libc, and it is also the program the WebAssembly
page runs (§4).

**Measured on this Mac (M3 Pro, macOS 26.2), 2026-11-16.**

- **Setup.** The static example and the model server's Python path (`Nft2` over the shared `libarc.dylib`, the same
  call `/v1/meta` makes) used the installed ear (`~/Library/Application Support/Outpost Luna/assets/ear/nft2`, read in
  place and never written), ONNX Runtime 1.32.0 (pinned) and 4 threads.
- **Clips.** All 40 golden clips (`desktop/tests/golden`), each run twice: with no names list, and with the 21 golden
  names.
- **Result.** **80/80 identical:** text, decoder text, every word with its times and tag, names (heard, entity,
  state), numbers and events. For example, c11_0 gives "Send the rover to Shackleton", with Shackleton tagged
  `ENTITY_LUNAR` at 1.68–2.32 s.
- **Timing.** The model loads in 1.2–1.6 s. A 3–4 s clip decodes in a median of 171 ms (80 runs), and in about 0.55 s
  on a process's first call.
- **Binary.** `transcribe` links only `libSystem` (`otool -L`). libarc is inside it, and ONNX Runtime is loaded at run
  time.

## 2. The C API contract

`include/arc.h` is the contract. The bindings are generated from it (`model_server/tools/gen_bindings.py`), and its
`ARC_ABI_VERSION` bump rules apply to every embedder.

- **Check the ABI at startup.** Compare `arc_abi_version()` with the `ARC_ABI_VERSION` you compiled against, and
  refuse to run if they differ. With a static library they always match, unless headers from another checkout were
  used.
- **Lifecycle.**

  ```
  arc_ort_set_library  ->  arc_nft2_create(dir, threads)
                       ->  [arc_nft2_set_names / arc_nft2_set_context]
                       ->  arc_nft2_transcribe  or  arc_nft2_stream_open / feed / flush / close
                       ->  arc_result_free (every result)  ->  arc_nft2_destroy
  ```

- **Errors.** A failed call returns NULL or -1, and the message comes from `arc_last_error()` (thread-local) or from the
  `err` buffer of `*_create`.
- **Memory.** Every `arc_result*` belongs to the caller and must be freed with `arc_result_free`. Strings inside a
  result live as long as the result. Names and context are copied, so the caller's buffers can be freed after the
  call.
- **Audio.** 16 kHz, mono, float in [-1, 1]. PCM16 is converted with `x / 32768`, as the model server does.
- **Threading: one model, one call at a time.** An `arc_nft2*` is not safe for concurrent use.
  - Every call on a model, *and* on the streams opened from it, must be serialized: the model server holds `Nft2.lock`
    for this.
  - Different models can run on different threads, but each one is a full copy of the weights (0.6–0.9 GB RSS).
  - libarc runs its own pool of `threads` workers inside a call, so do not call it from many threads to get
    parallelism.
  - `arc_ort_set_library` must be called once, before the first create.
- **The model folder** is opened read-only. libarc never writes to it. As in the model server, check the files against
  their manifest's sha256 before you load them (`model_verify.py`); libarc does not.
- **Coming in Phase 2** (`docs/ENGINE_SERVICE.md` §5.1): `arc_runtime` / `arc_nft2_model` / `arc_nft2_create_from`
  (one copy of the weights, many contexts), `arc_nft2_cancel` and streaming partials. These additions will raise the
  minor version of `ARC_VERSION`. `arc_nft2_create` stays as the one-call path for in-process users.

## 3. Mobile

The same static library builds for iOS and Android with their CMake toolchains. Neither has been built or run yet.

- **iOS:** use `-DARC_ORT_LINKED=ON` with ONNX Runtime's `onnxruntime-c` static xcframework.
- **Android:** use the NDK toolchain with `libonnxruntime.so` from the AAR. The default loader works with an absolute
  path inside the app's native library folder.

Memory is the constraint. The ear needs 0.6–1.0 GB RSS (docs/LOCAL_EAR.md), which is too much for low-end phones.

## 4. WebAssembly

**Status: works (spike).** The ear loads and transcribes golden clips in a headless Chromium, entirely in the page,
with libarc compiled to WebAssembly and the encoder and RNNT nets on onnxruntime-web. The output matches the native
build (numbers below). It is a spike: tested in one browser on one machine, with no streaming API and no caching of the
461 MB download. The rest of this section says what is built and what is left.

### 4.1 Can libarc call ONNX Runtime's C API in the browser?

**Not with the published packages.** We checked the npm package `onnxruntime-web` 1.31.1, the newest stable release;
1.32.0 is only on the dev channel.

- **The WebAssembly module.** `dist/ort-wasm-simd-threaded.wasm` (14.8 MB) imports its memory and exports 55
  functions, all with minified names (`Wa`, `Xa`, …). `OrtGetApiBase` is not among them.
- **The JavaScript glue.** `ort-wasm-simd-threaded.mjs` binds those exports to a private, flat API of ONNX Runtime's
  WebAssembly layer (`onnxruntime/wasm/api.h`): `_OrtCreateSession`, `_OrtRun`, `_OrtCreateTensor`, `_OrtGetTensorData`
  and so on. This API is internal, undocumented and changes between versions. It is not the `OrtApi` C API that
  `arc_nft2_ort.c` uses.
- **Conclusion.** A C program cannot link `arc_nft2_ort.c` against the npm artifacts.

The only way to get the real C API inside WebAssembly is to **build ONNX Runtime from source** with
`./build.sh --build_wasm_static_lib` (onnxruntime.ai/docs/build/web.html). That produces
`libonnxruntime_webassembly.a`, which you link together with the C API headers; you need the same emsdk version as
ONNX Runtime used, and no prebuilt copy is published. With that library, libarc's existing backend links unchanged:

```bash
emcmake cmake -S desktop/vendor/libarc -B build/libarc-wasm-ort -DARC_NFT2_BACKEND=ort -DARC_ORT_LINKED=ON
# then link your program with build/libarc-wasm-ort/static/libarc.a + libonnxruntime_webassembly.a
```

We compiled that configuration (`static/libarc.a` builds). It is **not linked or run** here: ONNX Runtime's source
tree plus its WebAssembly build need several GB of disk and about an hour, and this spike had a 2.5 GB budget.

### 4.2 What is built: the `web` backend

The NFT2 nets sit behind six functions (`src/arc_nft2_be.h`). `src/arc_nft2_web.c` implements those six with
onnxruntime-web's **public** JavaScript API (`InferenceSession`, `Tensor`), called from C through `EM_ASYNC_JS`:

- **Encoder graphs.** Edited in C exactly as the native backend edits them: the Arc tap is appended as a graph output.
  That protobuf code moved, unchanged, into `src/arc_onnx_pb.c`. Their external data (`encoder.weights`, 282 MB) goes
  straight to onnxruntime-web as a `Uint8Array` and never enters libarc's heap.
- **Asynchronous runs.** `InferenceSession.run` is asynchronous, so the program is linked with `-sASYNCIFY`. The C
  stack suspends while a graph runs, and `arc.wasm` is 0.45 MB.
- **Everything else** in libarc is unchanged C: the log-mel front end, RNNT greedy decoding with biasing, the Arc
  decoder (q4), linking, numbers and events.
- **The program.** The page runs `examples/transcribe.c` itself with `callMain`.

```bash
emcmake cmake -S desktop/vendor/libarc -B desktop/build/libarc-wasm -DARC_NFT2_BACKEND=web -DARC_BUILD_EXAMPLES=ON
cmake --build desktop/build/libarc-wasm                    # -> arc.mjs + arc.wasm (+ static/libarc.a)
desktop/vendor/libarc/wasm/fetch_ort_web.sh                # onnxruntime-web 1.31.1 -> wasm/ort/ (integrity-checked)
python3 desktop/vendor/libarc/wasm/serve.py --model <nft2 dir>          # http://127.0.0.1:47931/ (loopback only)
node desktop/vendor/libarc/wasm/headless.mjs "http://127.0.0.1:47931/?clip=c11_0"   # silent headless run -> JSON
```

`wasm/index.html` + `main.mjs` work as follows:

1. Fetch the `nft2/` folder: 461 MB.
2. Put 179 MB of it into the Emscripten file system. libarc's C reads that part (configs, tokenizer, safetensors,
   graphs).
3. Hand `encoder.weights` to onnxruntime-web.
4. Run `transcribe /nft2 (linked) /clip.wav --threads 1 [--names ...]` and show the JSON (`window.arcResult`).

`?clip=` picks a golden clip (served from `desktop/tests/golden/audio`), and `?names=` sets a names list.

**Measured** in headless Chromium (Chrome for Testing 156, Playwright's `chrome-headless-shell`) on this Mac, with
Emscripten 7.0.0 and onnxruntime-web 1.31.1. The comparison is with the native static build (§1) on the same 80 runs
(40 golden clips, with and without the names list):

| | Browser (`web` backend) | Native static example |
|---|---|---|
| Same text, decoder text, tags, names (heard / entity / state), numbers, events | **80/80** | (reference) |
| Also the same word times, to 10 ms | 78/80: in c14_1 "Vavilov's" starts at 1.36 s instead of 1.44 s (one 80 ms encoder frame); onnxruntime-web's wasm kernels round differently from native MLAS | |
| Model load (`arc_nft2_create`) | median 1.47 s (the files already in memory) | 1.2–1.6 s |
| Decode, 3–4 s clip | median **720 ms** (ORT 4 threads, libarc 1 thread) | median 171 ms (4 threads) |
| Fetch of the 461 MB from loopback | 0.2–0.4 s (a real network will dominate) | n/a |
| Memory | libarc's heap 387 MB, JS heap 553 MB, all headless-Chromium processes together at most **2.4 GB** RSS | 0.6–1.0 GB RSS |
| Binary | `arc.wasm` 0.45 MB + `arc.mjs` 72 KB; onnxruntime-web 14.8 MB | |

The page was cross-origin isolated (`serve.py` sends COOP/COEP), so onnxruntime-web used 4 threads.

### 4.3 What blocks a real browser version, and the plan

| Issue | Today | Plan |
|---|---|---|
| **Download size** | 461 MB on every first visit (weights 282 MB, decoder 96 MB, q4 trunk 37 MB, adapters 19 MB, graphs 22 MB) | Store it in the Cache API or OPFS after the first visit, keyed by the manifest sha256, and fetch it in parallel with progress. Shrinking `encoder.weights` is a model question (ENGINE_SERVICE Q5) and needs a golden-gated eval |
| **Memory** | see the table above. Two encoder sessions each copy `encoder.weights` into onnxruntime-web's heap, and wasm32 memory is capped at 4 GB per module | Run one encoder session with a per-chunk "first" flag, or export one graph, to drop one copy. Release the fetched `Uint8Array` after session creation. Then test on 8 GB Chromebooks |
| **Threads** | libarc is single-threaded in wasm (no `-pthread`; its pool runs serially). onnxruntime-web uses 4 threads only when the page is cross-origin isolated (COOP `same-origin` + COEP `require-corp`, which `serve.py` sends); otherwise it uses 1 | Ship COOP/COEP on the hosting origin. Building libarc with `-pthread` (needs the same isolation) is the next speed step |
| **Asynchronous runs** | Asyncify instruments the call stack: larger and slower code | Use `-sJSPI` (JS Promise Integration) where browsers have it, and keep Asyncify as the fallback |
| **Streaming** | whole clips only (`arc_nft2_transcribe`); the page is a test harness | Export the `arc_nft2_stream_*` API to JavaScript and feed it from an `AudioWorklet` at 16 kHz in a Worker. Live partials wait for Phase 2's RNNT streaming partials |
| **Browsers** | only headless Chromium 156 has been run | Safari (wasm memory limits on iOS) and Firefox |
| **The real C API** | `ARC_NFT2_BACKEND=ort` + `ARC_ORT_LINKED` compiles but is not linked (§4.1) | Build `libonnxruntime_webassembly.a` 1.32.0 on a machine with disk space, link it, and compare it with the `web` backend for size and speed. It would remove the JavaScript bridge |
| **Licence** | the model is CC BY-NC 4.0 and libarc is CC BY-NC 4.0 | Serving the weights to browsers publishes them: an owner decision before any public page |
