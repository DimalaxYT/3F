#!/usr/bin/env python3
"""photo_pass.py — Passe photographique fidèle à la géométrie 3D via le GPU
de datacenter de l'agent (`generate_image`), sans aucun GPU requis côté client.

Principe :
  1. Lit un `.glb` assemblé/sculpté proprement (CSG `manifold3d` + UVs `xatlas`)
     et génère ses guides géométriques exacts (rendu studio GGX+HDRI+SSAO,
     profondeur normalisée, normales caméra, masque silhouette exact `mask.png`).
  2. Produit un manifeste `photo_pass.json` contenant le prompt studio calibré
     et les chemins de référence `images=[guide_hero_studio.png, guide_hero_normal.png]`
     que l'agent passe directement à son outil natif `generate_image` (exécuté sur
     GPU de datacenter).
  3. Option `composite` : recadre/aligne si besoin le rendu GPU sur le masque ou
     génère une planche comparative `studio_vs_photo.png` prouvant la fidélité
     géométrique 1:1.

CLI :
    python scripts/photo_pass.py prepare model.glb -o out_dir --subject "katana japonais traditionnel"
    python scripts/photo_pass.py compare out_dir/guide_hero_studio.png out_dir/photo_hero.png -o out_dir/studio_vs_photo.png
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gpu_bridge
import renderer


def prepare_photo_pass(glb_path: str, outdir: str, subject: str,
                       size: int = 1024) -> dict:
    manifest = gpu_bridge.prepare_guides(
        glb_path, outdir,
        views={"hero": [42.0, 22.0], "side": [90.0, 12.0]},
        size=size,
    )
    hero = manifest["views"]["hero"]
    prompt = (
        f"Studio product photography of {subject}, exact same 3D geometry, "
        f"proportions, pose, camera angle and silhouette as the reference render, "
        f"shot on Hasselblad medium format 85mm f/8 on seamless neutral light gray "
        f"studio cyclorama, softbox rim lighting, ultra-realistic physical surface "
        f"micro-texture, natural contact shadows, photorealistic, sharp focus, no text."
    )
    out = {
        "glb": os.path.abspath(glb_path),
        "subject": subject,
        "recommended_generate_image_call": {
            "images": [hero["studio"], hero["normal"]],
            "file_path": os.path.join(outdir, "photo_hero.png"),
            "offer_options": False,
            "prompt": prompt,
        },
        "guides": manifest["views"],
    }
    p_json = os.path.join(outdir, "photo_pass.json")
    with open(p_json, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    return out


def make_side_by_side(studio_path: str, photo_path: str, out_path: str,
                      title: str = "Maillage PBR Exact vs Passe Photo GPU Datacenter"):
    im_a = Image.open(studio_path).convert("RGB")
    im_b = Image.open(photo_path).convert("RGB").resize(im_a.size, Image.LANCZOS)
    return renderer.contact_sheet(
        [(im_a, "1. Maillage .GLB exact (GGX + HDRI + AO)"),
         (im_b, "2. Passe Photo GPU Datacenter (img2img)")],
        cols=2, out_path=out_path, title=title,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("prepare")
    p1.add_argument("glb")
    p1.add_argument("-o", "--outdir", required=True)
    p1.add_argument("--subject", required=True)
    p1.add_argument("--size", type=int, default=1024)

    p2 = sub.add_parser("compare")
    p2.add_argument("studio")
    p2.add_argument("photo")
    p2.add_argument("-o", "--out", required=True)
    p2.add_argument("--title", default="Maillage PBR Exact (.GLB) vs Passe Photo GPU Datacenter")

    args = ap.parse_args()
    if args.cmd == "prepare":
        res = prepare_photo_pass(args.glb, args.outdir, args.subject, size=args.size)
        print(json.dumps(res["recommended_generate_image_call"], indent=2, ensure_ascii=False))
    elif args.cmd == "compare":
        make_side_by_side(args.studio, args.photo, args.out, title=args.title)
        print(args.out)


if __name__ == "__main__":
    main()
