#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare.py — boucle qualité image → 3D : silhouette du mesh vs photo de référence.

    python compare.py --mesh out/obj/obj.glb --ref photo.png --axes xz --out out/cmp
    python compare.py --render render.png --ref photo.png --out out/cmp

Principe : les deux silhouettes sont mises à l'échelle sur la même hauteur,
alignées par centre de bbox, puis comparées (IoU global + IoU par tiers
vertical). Trous rebouchés des deux côtés : on compare l'enveloppe
(proportions globales), pas les détails internes.

Overlay : ROUGE = référence seule, VERT = mesh seul, JAUNE = accord.
"""
from __future__ import annotations
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import img2mesh as i2m                                 # noqa: E402  (segmentation)
import trimesh                                         # noqa: E402

CANVAS = 720


def _to_mesh(m):
    if isinstance(m, trimesh.Trimesh):
        return m
    if hasattr(m, "dump"):
        return m.dump(concatenate=True)
    raise ValueError("objet trimesh inattendu : %r" % type(m))


def mesh_silhouette(mesh_or_path, axes="xz", canvas=CANVAS):
    """Masque booléen de la silhouette projetée (vue orthographique)."""
    m = _to_mesh(trimesh.load(mesh_or_path, force="scene")
                 if isinstance(mesh_or_path, str) else mesh_or_path)
    i, j = {"xz": (0, 2), "yz": (1, 2), "xy": (0, 1)}[axes]
    P = np.asarray(m.vertices)[:, [i, j]].astype(float)
    lo = P.min(0)
    size = P.max(0) - lo
    H = float(canvas)
    s = (H - 8.0) / max(size.max(), 1e-9)
    W = int(round(size[0] * s)) + 8
    Q = (P - lo) * s
    Q[:, 0] += 4.0
    Q[:, 1] = (H - 4.0) - Q[:, 1]                      # y image vers le bas
    im = Image.new("L", (int(W), int(H)), 0)
    dr = ImageDraw.Draw(im)
    for f in np.asarray(m.faces):
        dr.polygon([tuple(Q[k]) for k in f], fill=255)
    return np.asarray(im) > 127


def _crop_resize(mask, canvas=CANVAS):
    ys, xs = np.where(mask)
    if len(ys) == 0:
        raise ValueError("masque vide")
    m = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = m.shape
    s = (canvas - 8.0) / max(h, 1)
    im = Image.fromarray((m * 255).astype(np.uint8)).resize(
        (max(1, int(round(w * s))), canvas - 8), Image.NEAREST)
    return np.asarray(im) > 127


def _paste_center(mask, H, W):
    cv = np.zeros((H, W), bool)
    y0 = (H - mask.shape[0]) // 2
    x0 = (W - mask.shape[1]) // 2
    cv[y0:y0 + mask.shape[0], x0:x0 + mask.shape[1]] = mask
    return cv


def score_masks(ref_mask, mesh_mask, fill_holes=True, thirds=3):
    """IoU global + par tiers vertical, après normalisation hauteur/centre."""
    a = ndimage.binary_fill_holes(_crop_resize(ref_mask)) if fill_holes \
        else _crop_resize(ref_mask)
    b = ndimage.binary_fill_holes(_crop_resize(mesh_mask)) if fill_holes \
        else _crop_resize(mesh_mask)
    H = max(a.shape[0], b.shape[0])
    W = max(a.shape[1], b.shape[1])
    A, B = _paste_center(a, H, W), _paste_center(b, H, W)
    iou = float((A & B).sum()) / max(float((A | B).sum()), 1.0)
    zones = []
    for k in range(thirds):
        aa = A[k * H // thirds:(k + 1) * H // thirds]
        bb = B[k * H // thirds:(k + 1) * H // thirds]
        zones.append(round(float((aa & bb).sum()) / max(float((aa | bb).sum()), 1.0), 4))
    ar = lambda m: round(m.shape[1] / m.shape[0], 4)
    return {"iou": round(iou, 4),
            "iou_zones": {["haut", "milieu", "bas"][k] if thirds == 3 else
                          str(k): zones[k] for k in range(thirds)},
            "ref_aspect": ar(a), "mesh_aspect": ar(b)}, A, B


def overlay(A, B, path):
    ov = np.zeros((A.shape[0], A.shape[1], 3), np.uint8)
    ov[..., 0] = np.where(A & ~B, 255, np.where(A & B, 190, 0))   # ref → rouge
    ov[..., 1] = np.where(B & ~A, 255, np.where(A & B, 190, 0))   # mesh → vert
    Image.fromarray(ov).save(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="3d-forge compare (IoU silhouette)")
    ap.add_argument("--mesh", help="GLB/OBJ/STL du mesh à évaluer")
    ap.add_argument("--render", help="rendu PNG à évaluer (fond doit être uni)")
    ap.add_argument("--ref", required=True, help="photo/rendu de référence")
    ap.add_argument("--axes", default="xz", choices=["xz", "yz", "xy"],
                    help="projection vue du mesh : xz=profil, yz=face, xy=dessus")
    ap.add_argument("--tol", type=float, default=0.14)
    ap.add_argument("--out", default="out/compare")
    args = ap.parse_args(argv)
    if not (args.mesh or args.render):
        ap.error("--mesh ou --render requis")

    ref_a = i2m.load_rgba(args.ref)
    ref_mask, _ = i2m.segment(ref_a, tol=args.tol)

    if args.mesh:
        mesh_mask = mesh_silhouette(args.mesh, axes=args.axes)
    else:
        mesh_mask, _ = i2m.segment(i2m.load_rgba(args.render), tol=args.tol)

    sc, A, B = score_masks(ref_mask, mesh_mask)
    os.makedirs(args.out, exist_ok=True)
    overlay(A, B, os.path.join(args.out, "overlay.png"))
    sc.update({"ref": os.path.basename(args.ref),
               "candidate": os.path.basename(args.mesh or args.render),
               "axes": args.axes if args.mesh else "render"})
    with open(os.path.join(args.out, "score.json"), "w") as f:
        json.dump(sc, f, indent=1)
    print(json.dumps(sc, ensure_ascii=False, indent=1))
    return 0 if sc["iou"] >= 0.60 else 1


if __name__ == "__main__":
    sys.exit(main())
