"""Serve the libarc WebAssembly page (index.html) on loopback with the headers it needs, for a local test only.

    python3 desktop/vendor/libarc/wasm/serve.py --model <nft2 dir> [--build desktop/build/libarc-wasm] [--port 47931]

/            this folder (index.html, main.mjs, ort/ from fetch_ort_web.sh)
/build/      the Emscripten build (arc.mjs, arc.wasm)
/model/      the nft2/ folder, read only (never written)
/clip/       desktop/tests/golden/audio
COOP same-origin + COEP require-corp make the page cross-origin isolated, so onnxruntime-web may use threads
(SharedArrayBuffer). Binds 127.0.0.1 only. Stdlib only."""
import argparse
import functools
import http.server
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


class Handler(http.server.SimpleHTTPRequestHandler):
    roots: dict = {}

    def translate_path(self, path):
        p = path.split("?", 1)[0].split("#", 1)[0]
        for prefix, root in self.roots.items():
            if p.startswith(prefix):
                rel = Path(*[s for s in p[len(prefix):].split("/") if s and s != ".."])
                return str(Path(root) / rel)
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


Handler.extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".mjs": "text/javascript",
                          ".wasm": "application/wasm"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="the nft2/ folder")
    ap.add_argument("--build", default=str(REPO / "desktop/build/libarc-wasm"))
    ap.add_argument("--port", type=int, default=47931)
    a = ap.parse_args()
    Handler.roots = {"/build/": a.build, "/model/": a.model, "/clip/": str(REPO / "desktop/tests/golden/audio")}
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), functools.partial(Handler, directory=str(HERE)))
    print(f"http://127.0.0.1:{a.port}/", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
