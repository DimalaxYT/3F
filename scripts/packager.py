#!/usr/bin/env python3
"""
packager.py — empaquetage automatique en archive `.zip` prête à télécharger (`<name>.zip`).

Chaque génération `3d-forge` produit dans `<out_dir>/<name>.zip` un bundle complet,
autonome et léger contenant :
  - `<name>_game.glb`, `<name>_LOD1.glb`, `<name>_LOD2.glb`, `<name>_colliders.glb`
  - `<name>.stl` (et `.obj` / `.usdz` si générés)
  - `roblox/`, `unreal/`, `unity/`, `godot/`, `parts/`
  - `qa_game_sheet.png`, `photo_match.png` (si généré depuis photo), `qa_summary.md`, `game_manifest.json`
"""
from __future__ import annotations

import zipfile
from pathlib import Path

_SKIP_SUFFIXES = {".zip", ".pyc", ".html"}
_SKIP_DIRS = {"__pycache__", "ai_gpu", "refs_tmp"}


def build_asset_zip(out_dir: str | Path, name: str | None = None, zip_name: str | None = None) -> str:
    """Crée `<out_dir>/<name>.zip` (compression `ZIP_DEFLATED` rapide niveau 6) et retourne son chemin."""
    root = Path(out_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Dossier introuvable pour l'archive ZIP : {root}")

    stem = (name or root.name).strip() or "asset_3d"
    out_zip = root / (zip_name or f"{stem}.zip")
    tmp_zip = root / f".{stem}.zip.tmp"

    files_to_pack: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in _SKIP_DIRS or part.startswith(".") for part in rel.parts):
            continue
        if p.suffix.lower() in _SKIP_SUFFIXES:
            continue
        files_to_pack.append(p)

    with zipfile.ZipFile(tmp_zip, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in files_to_pack:
            arcname = f"{stem}/{p.relative_to(root).as_posix()}"
            zf.write(p, arcname=arcname)

    tmp_zip.replace(out_zip)
    return str(out_zip)
