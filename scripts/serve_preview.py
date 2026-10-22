#!/usr/bin/env python3
"""
serve_preview.py — sert un dossier d'asset 3D en HTTP multi-thread sur 0.0.0.0 (live preview).

    python3 scripts/serve_preview.py exports/<nom> --port 8003 --host 0.0.0.0

  - `/` sert automatiquement `preview.html`
  - `?download=1` ou `.glb` / `.stl` / `.fbx` / `.obj` envoie `Content-Disposition: attachment`
    pour garantir le téléchargement natif dans tous les navigateurs et iframes Live Preview.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
import urllib.parse
from pathlib import Path


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class PreviewHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".glb": "model/gltf-binary",
        ".gltf": "model/gltf+json",
        ".stl": "model/stl",
        ".webp": "image/webp",
    }

    def end_headers(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        fname = Path(urllib.parse.unquote(parsed.path)).name
        is_dl = "download=1" in parsed.query or Path(fname).suffix.lower() in {".glb", ".stl", ".obj", ".fbx", ".zip"}
        if is_dl and fname:
            self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path in ("/", "") and (Path(self.directory) / "preview.html").is_file():
            self.path = "/preview.html"
        super().do_GET()

    def do_HEAD(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path in ("/", "") and (Path(self.directory) / "preview.html").is_file():
            self.path = "/preview.html"
        super().do_HEAD()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", help="dossier de sortie contenant preview.html et les .glb/.stl")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args(argv)

    d = Path(args.dir)
    if not d.is_dir():
        print(f"dossier introuvable : {d}", file=sys.stderr)
        return 1
    handler = functools.partial(PreviewHTTPRequestHandler, directory=str(d))
    with ThreadingTCPServer((args.host, args.port), handler) as httpd:
        print(f"[serve_preview] http://{args.host}:{args.port}/  (dossier {d})", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
