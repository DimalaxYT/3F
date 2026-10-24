#!/usr/bin/env python3
"""Planche de comparaison référence / modèle — `compare_reference.png`.

    PYTHONPATH=scripts python3 examples/g36_rifle/compare_reference.py

Trois panneaux à la **même échelle** (1 px = 1 mm) :

1. la photo de référence, recadrée et remise à l'échelle ;
2. la silhouette du modèle en projection orthographique ;
3. la superposition (rouge = manquant, bleu = en trop, blanc = commun).

Plus un encart 3/4 qui montre la forme en volume — c'est lui qui rattrape les
erreurs qu'un profil plat laisse passer.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(HERE))

import refcheck as rc  # noqa: E402


def main() -> int:
    import renderer as rn

    mod = rc.load_model()
    A = rc.ref_mask()
    B = rc.model_mask(mod)
    h, w = A.shape

    # 1. photo remise à l'échelle du canevas millimétrique
    photo = Image.open(rc.REF).convert("RGB").crop(rc.REF_BOX)
    photo = photo.resize((w, h), Image.LANCZOS)

    # 2. silhouette du modèle
    body = np.full((h, w, 3), 24, np.uint8)
    body[B] = (214, 214, 210)
    body_img = Image.fromarray(body)

    # 3. superposition
    rgb = np.full((h, w, 3), 20, np.uint8)
    rgb[A] = (236, 68, 68)
    rgb[B] = (66, 132, 236)
    rgb[A & B] = (242, 242, 242)
    over = Image.fromarray(rgb)

    # encart 3/4 — rendu du GLB EXPORTÉ quand il existe : le Builder nu ne
    # montre ni la patine, ni l'albédo, ni l'ORM.
    glb = ROOT / "exports" / "g36_rifle" / "g36_rifle_game.glb"
    if glb.is_file():
        import trimesh
        sc = trimesh.load(str(glb), force="scene")
    else:
        sc = mod.ground(mod.build()).scene()
    q34 = rn.render_view(sc, -128.0, 16.0, size=760, ssaa=1.4, fov=27.0, post=True)
    q34.thumbnail((w, 560), Image.LANCZOS)

    pad = 14
    label_h = 26
    sheet_h = pad + (label_h + h + pad) * 3 + q34.height + pad
    sheet = Image.new("RGB", (w + 2 * pad, sheet_h), (16, 16, 18))
    dr = ImageDraw.Draw(sheet)

    y = pad
    for title, img in (("PHOTO — H&K G36, profil gauche", photo),
                       ("MODÈLE — projection orthographique, 1 px = 1 mm", body_img),
                       ("SUPERPOSITION — rouge : manquant · bleu : en trop", over)):
        dr.text((pad, y), title, fill=(235, 235, 235))
        y += label_h
        sheet.paste(img, (pad, y))
        y += h + pad

    dr.text((pad, y + 4), "MODÈLE FINAL — GLB texturé, vue 3/4", fill=(235, 235, 235))
    sheet.paste(q34, (pad, y + 30))

    out = HERE / "compare_reference.png"
    sheet.save(out)

    inter = int((A & B).sum())
    union = int((A | B).sum())
    print(f"IoU {inter / union:.4f} · manque {int((A & ~B).sum())} mm² · "
          f"en trop {int((B & ~A).sum())} mm²")
    print(f"planche -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
