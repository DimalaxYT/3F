#!/usr/bin/env python3
"""Planche de matériaux — `material_sheet.png`.

    PYTHONPATH=scripts python3 examples/g36_rifle/material_sheet.py

Rend le **GLB exporté, textures comprises**, pas le maillage brut : c'est le
seul contrôle qui montre ce que l'artiste reçoit. Le rendu du Builder nu ne dit
rien de la patine, de l'albédo ni de l'ORM — et c'est précisément là que se
cachaient les défauts (classification des matériaux, taches d'AO, acier noir
qui brillait comme du chrome).

Quatre panneaux : trois vues du GLB + une bande de mesures d'image
(luminance d'albédo comparée à celle de la photo, écart-type, AO).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import renderer as rn  # noqa: E402

GLB = ROOT / "exports" / "g36_rifle" / "g36_rifle_game.glb"
REF = ROOT / "image-search" / "g36-official-left-profile-rails.png"
REF_BOX = (198, 92, 1474, 449)
BC = ROOT / "exports" / "g36_rifle" / "unreal" / "T_g36_rifle_BC.png"
ORM = ROOT / "exports" / "g36_rifle" / "unreal" / "T_g36_rifle_ORM.png"


def lum(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def main() -> int:
    if not GLB.is_file():
        print("GLB absent — lance d'abord export_game_package", file=sys.stderr)
        return 1

    scene = trimesh.load(GLB, force="scene")
    views = [
        ("profil gauche", -90.0, 0.0, 34.0),
        ("3/4 avant", -128.0, 16.0, 27.0),
        ("3/4 arriere", -38.0, 18.0, 27.0),
    ]
    panels = []
    for title, az, el, fov in views:
        img = rn.render_view(scene, az, el, size=760, ssaa=1.3, fov=fov, post=True)
        panels.append((title, img))

    # ---- bande de mesures -------------------------------------------------
    stats = []
    if BC.is_file():
        bc = np.asarray(Image.open(BC).convert("RGB")).astype(float)
        m = bc.sum(2) > 8
        lb = lum(bc)[m]
        stats.append(f"albedo : mediane {np.median(lb):5.1f}   ecart-type {lb.std():4.1f}"
                     f"   p5 {np.percentile(lb, 5):4.0f}   p95 {np.percentile(lb, 95):4.0f}")
    if ORM.is_file():
        orm = np.asarray(Image.open(ORM).convert("RGB")).astype(float)
        mm = orm.sum(2) > 8
        stats.append(f"AO {np.median(orm[:, :, 0][mm]):.0f}/255"
                     f"   rugosite {np.median(orm[:, :, 1][mm]) / 255:.2f}"
                     f"   metal moyen {orm[:, :, 2][mm].mean() / 255:.2f}")
    if REF.is_file():
        p = np.asarray(Image.open(REF).convert("RGB").crop(REF_BOX)).astype(float)
        lp = lum(p[95:140, 860:1000])       # flanc du boîtier, sans reflet
        stats.append(f"reference photo (flanc boitier) : mediane {np.median(lp):.0f}"
                     f"   ecart-type {lp.std():.0f}")

    pad, label = 12, 24
    w, h = panels[0][1].width, panels[0][1].height
    cols = 3
    rows = 1
    foot = 104
    sheet = Image.new("RGB", (pad + cols * (w + pad), pad + rows * (h + label + pad) + foot),
                      (16, 16, 18))
    d = ImageDraw.Draw(sheet)
    x = pad
    for title, img in panels:
        d.text((x, pad), title.encode("ascii", "replace").decode(), fill=(235, 235, 235))
        sheet.paste(img, (x, pad + label))
        x += w + pad

    y = pad + h + label + pad + 6
    for line in stats:
        d.text((pad, y), line.encode("ascii", "replace").decode(), fill=(150, 210, 170))
        y += 20
    d.text((pad, y + 2), "rendu = GLB exporte avec ses cartes PBR", fill=(140, 140, 150))

    out = HERE / "material_sheet.png"
    sheet.save(out)
    for s in stats:
        print(s)
    print(f"planche -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
