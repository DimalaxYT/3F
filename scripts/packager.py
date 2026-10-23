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

import hashlib
import zipfile
from pathlib import Path

_SKIP_SUFFIXES = {".zip", ".pyc", ".html"}

# Cartes DÉRIVÉES du bake 4K : elles restent sur disque (pratiques en local) mais
# n'ont pas leur place dans l'archive — `N_gl` est exactement `255 - N` et `AO`
# est exactement le canal R de l'ORM. Les embarquer doublerait le poids du ZIP
# sans apporter un octet d'information.
_DERIVED_SUFFIXES = ("_N_gl.png", "_AO.png")
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
        if p.name.endswith(_DERIVED_SUFFIXES):
            continue
        files_to_pack.append(p)

    # Déduplication par contenu : `unreal/T_*.png` sont des copies OCTET POUR OCTET
    # des atlas de `render_4k/` (35 Mo pour rien dans l'archive).
    seen: dict[str, str] = {}
    unique: list[Path] = []
    for p in files_to_pack:
        if p.stat().st_size < 1 << 20:          # la dédup ne vaut que pour les gros fichiers
            unique.append(p)
            continue
        h = hashlib.md5(p.read_bytes()).hexdigest()
        if h in seen:
            continue
        seen[h] = p.relative_to(root).as_posix()
        unique.append(p)
    files_to_pack = unique

    with zipfile.ZipFile(tmp_zip, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in files_to_pack:
            arcname = f"{stem}/{p.relative_to(root).as_posix()}"
            zf.write(p, arcname=arcname)

    tmp_zip.replace(out_zip)
    return str(out_zip)
