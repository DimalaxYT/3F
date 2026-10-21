#!/usr/bin/env python3
"""
fetch_examples.py — restaure les exemples lourds (~174 Mo) SANS stockage dupliqué.

    python3 scripts/fetch_examples.py                # tous les packs d'exemples
    python3 scripts/fetch_examples.py --only katana dragon_buste

Le dépôt ne garde en arbre que les exemples légers (`vase`, `chaise_scandinave`,
`rocket`, références de la CI visuelle). Les packs complets (game_ready Roblox/UE5,
turntables, sculptures) sont récupérés depuis le tarball GitHub existant
(codeload = objets déjà poussés, zéro upload supplémentaire) puis extraits dans
`examples/`. Les fichiers déjà présents ne sont pas écrasés sauf `--force`.
"""
from __future__ import annotations

import argparse
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "DimalaxYT/3F"
HEAVY = ["dragon_buste", "epee_rouillee", "katana", "motocross", "sci_fi_crate"]


def tarball_url(ref: str) -> str:
    return f"https://codeload.github.com/{REPO}/tar.gz/refs/heads/{ref}"


def _safe_member(member: tarfile.TarInfo) -> bool:
    """Refuse les entrées capables d'écrire hors de `examples/` (traversée `..`,
    chemins absolus, liens symboliques/physiques)."""
    name = member.name
    parts = name.split("/")
    if name.startswith("/") or ".." in parts:
        return False
    if member.issym() or member.islnk():
        return False
    return True


def fetch(ref: str, only: list[str] | None, force: bool) -> int:
    want = set(only) if only else set(HEAVY)
    url = tarball_url(ref)
    print(f"[fetch] {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:
        raw = resp.read()
    extracted = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile() or not _safe_member(member):
                continue
            parts = member.name.split("/", 1)
            if len(parts) < 2 or not parts[1].startswith("examples/"):
                continue
            rel = parts[1]
            folder = rel.split("/")[1] if len(rel.split("/")) > 1 else ""
            if folder not in want:
                continue
            dest = ROOT / rel
            if dest.is_file() and not force:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tf.extractfile(member) as src, open(dest, "wb") as out:
                out.write(src.read())
            extracted += 1
    print(f"[fetch] {extracted} fichier(s) restauré(s) dans examples/ "
          f"({', '.join(sorted(want))})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", default="main", help="branche/tag source du tarball")
    ap.add_argument("--only", nargs="*", default=None, choices=HEAVY)
    ap.add_argument("--force", action="store_true", help="écrase les fichiers présents")
    args = ap.parse_args(argv)
    try:
        return fetch(args.ref, args.only, args.force)
    except Exception as exc:
        print(f"[fetch] échec réseau : {exc}\n"
              f"        les exemples légers (vase/chaise/rocket) restent utilisables ;"
              f" la CI visuelle aussi.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
