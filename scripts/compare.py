#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare.py — boucle qualité image → 3D : silhouette du mesh vs photo de référence.

    python compare.py --mesh out/obj/obj.glb --ref photo.png --axes xz --out out/cmp
    python compare.py --render render.png --ref photo.png --out out/cmp

Améliorations clés :
  * Filtrage automatique de l'ombre portée au sol (`strip_ground_shadow`) sur les
    photos studio (plus d'énorme bloc rouge fictif sous un véhicule à roues !).
  * Comparaison fidèle des creux/ajours (`--no-fill-holes` disponible, et les
    arches ouvertes en bas comme le garde-au-sol d'une moto/chaise ne sont plus
    bouchées artificiellement).

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

import img2mesh as i2m                                 # noqa: E402
import trimesh                                         # noqa: E402

CANVAS = 720


def _to_mesh(m):
    if isinstance(m, trimesh.Trimesh):
        return m
    if hasattr(m, "to_geometry"):
        return m.to_geometry()
    if hasattr(m, "dump"):
        return m.dump(concatenate=True)
    raise ValueError("objet trimesh inattendu : %r" % type(m))


def strip_ground_shadow(rgba: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Supprime l'ombre douce projetée sur fond studio clair en bas de l'objet.

    Sur une photo studio à fond clair, l'ombre au sol est achromatique (faible
    saturation), floue (faible gradient local) et d'intensité intermédiaire
    (plus sombre que le blanc du fond mais nettement plus claire qu'un pneu noir).
    """
    ys, xs = np.where(mask)
    if len(ys) < 64:
        return mask
    rgb = rgba[..., :3] / 255.0
    alpha = rgba[..., 3] / 255.0
    ba = np.concatenate([alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]])
    if ba.mean() < 0.6:
        return mask  # PNG détouré en alpha : ombre déjà absente ou voulue
    br = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]], axis=0)
    bg = np.median(br, axis=0)
    bg_lum = float(0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2])
    if bg_lum < 0.65:
        return mask

    lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    mx = rgb.max(-1)
    sat = np.where(mx > 1e-6, (mx - rgb.min(-1)) / np.maximum(mx, 1e-6), 0.0)
    grad = np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1))

    y0, y1 = int(ys.min()), int(ys.max())
    band_top = y1 - max(4, int(0.14 * (y1 - y0 + 1)))
    in_bottom = np.zeros_like(mask)
    in_bottom[band_top:y1 + 1, :] = True

    # Ombre typique : grise (sat faible), sans contour net (grad faible), et
    # atténuation modérée par rapport au fond blanc (pas un pneu noir dense < 0.22)
    shadow_px = (in_bottom & mask & (sat < 0.14)
                 & (lum > 0.24 * bg_lum) & (grad < 0.42))
    cleaned = mask & ~shadow_px
    # Garde la composante principale pour éliminer les résidus d'ombre isolés
    lab, n = ndimage.label(cleaned)
    if n > 1:
        sizes = ndimage.sum(cleaned, lab, range(1, n + 1))
        cleaned = lab == (1 + int(np.argmax(sizes)))
    return cleaned if cleaned.sum() > 0.5 * mask.sum() else mask


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
    Q[:, 1] = (H - 4.0) - Q[:, 1]
    im = Image.new("L", (int(W), int(H)), 0)
    dr = ImageDraw.Draw(im)
    tri = Q[np.asarray(m.faces)]
    for pts in tri.tolist():
        dr.polygon([(pts[0][0], pts[0][1]),
                    (pts[1][0], pts[1][1]),
                    (pts[2][0], pts[2][1])], fill=255)
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
    ov[..., 0] = np.where(A & ~B, 255, np.where(A & B, 190, 0))
    ov[..., 1] = np.where(B & ~A, 255, np.where(A & B, 190, 0))
    Image.fromarray(ov).save(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="3d-forge compare (IoU silhouette)")
    ap.add_argument("--mesh", help="GLB/OBJ/STL du mesh à évaluer")
    ap.add_argument("--render", help="rendu PNG à évaluer (fond doit être uni)")
    ap.add_argument("--ref", required=True, help="photo/rendu de référence")
    ap.add_argument("--axes", default="xz", choices=["xz", "yz", "xy"],
                    help="projection vue du mesh : xz=profil, yz=face, xy=dessus")
    ap.add_argument("--tol", type=float, default=0.14)
    ap.add_argument("--keep-shadow", action="store_true",
                    help="ne pas filtrer l'ombre portée au sol de la photo")
    ap.add_argument("--no-fill-holes", action="store_true",
                    help="évaluer aussi les ajours internes sans les boucher")
    ap.add_argument("--out", default="out/compare")
    args = ap.parse_args(argv)
    if not (args.mesh or args.render):
        ap.error("--mesh ou --render requis")

    ref_a = i2m.load_rgba(args.ref)
    ref_mask, _ = i2m.segment(ref_a, tol=args.tol)
    if not args.keep_shadow:
        ref_mask = strip_ground_shadow(ref_a, ref_mask)

    if args.mesh:
        mesh_mask = mesh_silhouette(args.mesh, axes=args.axes)
    else:
        r_a = i2m.load_rgba(args.render)
        mesh_mask, _ = i2m.segment(r_a, tol=args.tol)
        if not args.keep_shadow:
            mesh_mask = strip_ground_shadow(r_a, mesh_mask)

    sc, A, B = score_masks(ref_mask, mesh_mask, fill_holes=not args.no_fill_holes)
    os.makedirs(args.out, exist_ok=True)
    overlay(A, B, os.path.join(args.out, "overlay.png"))
    overlay(A, B, os.path.join(args.out, "silhouette_overlay.png"))
    sc.update({"ref": os.path.basename(args.ref),
               "candidate": os.path.basename(args.mesh or args.render),
               "axes": args.axes if args.mesh else "render",
               "shadow_filtered": not args.keep_shadow})
    with open(os.path.join(args.out, "score.json"), "w") as f:
        json.dump(sc, f, indent=1)
    print(json.dumps(sc, ensure_ascii=False, indent=1))
    return 0 if sc["iou"] >= 0.60 else 1


if __name__ == "__main__":
    sys.exit(main())
