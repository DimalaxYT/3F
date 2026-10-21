#!/usr/bin/env python3
"""
serve_preview.py — sert un dossier `out/` en HTTP sur 0.0.0.0 (live preview).

    python3 scripts/serve_preview.py out/<nom> --port 8000

Utile dans un sandbox type Arena.ai : le `preview.html` (viewer WebGL offline),
la `qa_game_sheet.png` et `qa_summary.md` s'ouvrent dans la live preview du
navigateur au lieu d'être téléchargés. Liens directs :
  /preview.html  /qa_game_sheet.png  /qa_summary.md  /gates.json
"""
from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", help="dossier de sortie turbo_forge/game_ready")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0",
                    help="0.0.0.0 par défaut : obligatoire pour les live previews proxyfiées")
    args = ap.parse_args(argv)

    d = Path(args.dir)
    if not d.is_dir():
        print(f"dossier introuvable : {d}", file=sys.stderr)
        return 1
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((args.host, args.port), handler) as httpd:
        print(f"[serve_preview] http://{args.host}:{args.port}/preview.html  (dossier {d})")
        print("  Ctrl-C pour stopper")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
