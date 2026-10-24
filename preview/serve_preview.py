#!/usr/bin/env python3
"""Serveur de preview — sert `preview/` et `exports/` derrière un seul port.

    python3 preview/serve_preview.py            # http://localhost:8000
    python3 preview/serve_preview.py --port 9000

Sert la racine du dépôt en statique, donc :
  /preview/index.html                     la page
  /preview/vendor/three.module.min.js     three.js vendorisé
  /exports/g36_rifle/g36_rifle_game.glb   le modèle (à générer avant)

Aucune restriction d'hôte/origine : la page fonctionne derrière un proxy
(ex. l'aperçu Arena sous https://<port>-<sandbox>.e2b.app) parce qu'elle
n'appelle que des URL relatives.
"""
from __future__ import annotations

import argparse
import http.server
import os
import socketserver
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "preview"

EXTRA_TYPES = {
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".webp": "image/webp",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".zip": "application/zip",
}


class Handler(http.server.SimpleHTTPRequestHandler):
    """Statique depuis la racine du dépôt, sans cache (dev)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def guess_type(self, path):  # noqa: D102
        ext = Path(str(path)).suffix.lower()
        return EXTRA_TYPES.get(ext) or super().guess_type(path)

    def end_headers(self):  # noqa: D102
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def _map_root(self):
        """`/` -> index.html. Pas de redirection : certains proxys ne
        réécrivent pas les chemins. Appliqué à GET **et** HEAD, sinon un
        contrôle de santé en HEAD reçoit le listing du dossier."""
        if self.path in ("/", "/preview", "/preview/"):
            self.path = "/preview/index.html"

    def do_GET(self):  # noqa: D102
        self._map_root()
        super().do_GET()

    def do_HEAD(self):  # noqa: D102
        self._map_root()
        super().do_HEAD()

    def log_message(self, fmt, *args):  # noqa: D102
        sys.stderr.write("  %s\n" % (fmt % args))


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    ap = argparse.ArgumentParser(description="Preview G36E")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--host", default="0.0.0.0",
                    help="0.0.0.0 pour être joignable derrière un proxy")
    args = ap.parse_args()

    glb = ROOT / "exports" / "g36_rifle" / "g36_rifle_game.glb"
    print(f"Preview  : http://localhost:{args.port}/preview/index.html")
    print(f"Dépôt    : {ROOT}")
    if glb.exists():
        print(f"Modèle   : {glb.relative_to(ROOT)}  ({glb.stat().st_size / 1e6:.1f} Mo)")
    else:
        print("Modèle   : ABSENT — lance d'abord", file=sys.stderr)
        print("           python3 scripts/turbo_forge.py g36 -o exports/g36",
              file=sys.stderr)
    with Server((args.host, args.port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\narrêt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
