#!/usr/bin/env python3
"""Contrôle de ressemblance du G36 — silhouettes comparées en millimètres réels.

    PYTHONPATH=scripts python3 examples/g36_rifle/refcheck.py

Les deux silhouettes sont rastérisées à **1 px = 1 mm** et projetées en
**orthographique** :

* la photo est rééchantillonnée avec son échelle mesurée (998 mm / 1276 px) ;
* le modèle est rastérisé en projetant ses triangles sur le plan (y, z) — des
  pièces fermées donnent donc exactement la silhouette orthographique.

Pourquoi pas `renderer.render_view` : sa caméra est **perspective** et cadre sur
la sphère englobante. Sur une arme de 61 mm de large vue à 1,1 m, ça déplace les
bords de 1 à 3 mm et ça fausse l'IoU — assez pour croire à une erreur de
géométrie qui n'existe pas.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

REF = ROOT / "image-search" / "g36-official-left-profile-rails.png"
REF_BOX = (198, 92, 1474, 449)

MM = 998.0                      # longueur réelle de l'arme
Y_SPAN = (-0.520, 0.520)        # fenêtre de comparaison, en mètres
Z_SPAN = (-0.215, 0.085)
PX_MM = 1.0                     # 1 px = 1 mm


def load_model():
    spec = importlib.util.spec_from_file_location("g36", HERE / "build_g36.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def canvas_shape():
    w = int(round((Y_SPAN[1] - Y_SPAN[0]) * 1000 * PX_MM))
    h = int(round((Z_SPAN[1] - Z_SPAN[0]) * 1000 * PX_MM))
    return h, w


def to_px(y_m, z_m):
    """(y, z) en mètres -> (colonne, ligne) du canevas millimétrique."""
    w = (Y_SPAN[1] - Y_SPAN[0]) * 1000 * PX_MM
    h = (Z_SPAN[1] - Z_SPAN[0]) * 1000 * PX_MM
    c = (y_m * 1000 - Y_SPAN[0] * 1000) * PX_MM
    r = (Z_SPAN[1] * 1000 - z_m * 1000) * PX_MM
    return c, r


def ref_mask() -> np.ndarray:
    """Masque de la photo, rééchantillonné à 1 px = 1 mm, fenêtres OUVERTES.

    Critère : luminance < 185 ou saturation > 0,05. La saturation est ce qui
    rattrape le chargeur, en polymère TRANSLUCIDE vert pâle : ses zones claires
    (199,210,196) ont une luminance de fond mais une saturation de 0,07.
    Ne PAS utiliser la distance à la couleur du fond : elle attrape l'ombre
    portée sous le canon et sous la crosse (+900 mm² d'aire fantôme).
    """
    im = Image.open(REF).convert("RGB").crop(REF_BOX)
    a = np.asarray(im).astype(int)
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1)
    # la teinte verte (G - max(R,B) >= 4) rattrape les facettes claires du
    # chargeur, alors que l'ombre portée est neutre : elle reste exclue
    green = a[:, :, 1] - np.maximum(a[:, :, 0], a[:, :, 2])
    m = (mx < 185) | (sat > 0.05) | (green >= 4)
    m = ndi.binary_closing(m, np.ones((3, 3)))
    lab, n = ndi.label(m)
    sizes = ndi.sum(m, lab, range(1, n + 1))
    m = lab == (int(np.argmax(sizes)) + 1)

    H, W = m.shape
    scale = MM / W                                   # mm par pixel de la photo
    seg = m[:, int(0.02 * W):int(0.12 * W)]
    ax = np.where(seg.any(axis=1))[0].mean()         # ligne de l'axe du canon

    out = np.zeros(canvas_shape(), bool)

    # chaque pixel du canevas (1 mm) reçoit la valeur du pixel photo correspondant
    hh, ww = out.shape
    cols = np.arange(ww)
    y_mm = Y_SPAN[0] * 1000 + cols / PX_MM
    src_x = np.clip(np.round((0.5 - y_mm / MM) * (W - 1)).astype(int), 0, W - 1)
    for r in range(hh):
        z_mm = Z_SPAN[1] * 1000 - r / PX_MM
        src_r = int(round(ax - z_mm / scale))
        if 0 <= src_r < H:
            out[r] = m[src_r][src_x]
    return out


def _runs(idx: np.ndarray):
    """Découpe un tableau d'indices croissants en plages contiguës."""
    brk = np.where(np.diff(idx) > 1)[0]
    starts = np.r_[idx[0], idx[brk + 1]]
    ends = np.r_[idx[brk], idx[-1]]
    return list(zip(starts, ends))


def model_mask(mod) -> np.ndarray:
    """Rastérisation orthographique des triangles projetés sur (y, z)."""
    b = mod.build()
    h, w = canvas_shape()
    img = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(img)
    for mesh, _mat, _lbl in b.parts:
        v = np.asarray(mesh.vertices)
        f = np.asarray(mesh.faces)
        cy, rz = to_px(0.0, 0.0)          # offsets
        # photo et modèle sont repérés par la MÊME fonction to_px : les deux
        # silhouettes ont donc la bouche du même côté du canevas, quel qu'il soit.
        ys = cy + v[:, 1] * 1000 * PX_MM
        zs = rz - v[:, 2] * 1000 * PX_MM
        for tri in f:
            dr.polygon([(ys[i], zs[i]) for i in tri], fill=255)
    return np.asarray(img) > 127


def main() -> int:
    mod = load_model()
    A = ref_mask()
    B = model_mask(mod)
    h, w = A.shape

    inter = int((A & B).sum())
    union = int((A | B).sum())
    iou = inter / union if union else 0.0
    print(f"canevas : {w} x {h} px (1 px = 1 mm)")
    print(f"IoU = {iou:.4f}   manque = {int((A & ~B).sum())} mm²   en trop = {int((B & ~A).sum())} mm²")

    # erreur de contour : écart du premier pixel de matière, en mm
    print("\n  y mm    photo      modèle      écart")
    print("        haut  bas   haut  bas   Δhaut Δbas")
    et = eb = 0.0
    n = 0
    for y_mm in range(-500, 501, 25):
        c, _ = to_px(y_mm / 1000, 0)
        c = int(round(c))
        if not (0 <= c < w):
            continue
        ca = np.where(A[:, c])[0]
        cb = np.where(B[:, c])[0]
        if not len(ca) or not len(cb):
            continue
        ta, ba = Z_SPAN[1] * 1000 - ca[0], Z_SPAN[1] * 1000 - ca[-1]
        tb, bb = Z_SPAN[1] * 1000 - cb[0], Z_SPAN[1] * 1000 - cb[-1]
        dt, db = tb - ta, bb - ba
        et += abs(dt)
        eb += abs(db)
        n += 1
        flag = "  <<<" if max(abs(dt), abs(db)) > 10 else ""
        print(f"  {y_mm:+5d} {ta:+6.0f} {ba:+5.0f} {tb:+6.0f} {bb:+5.0f}   {dt:+5.0f} {db:+5.0f}{flag}")
    print(f"\nerreur moyenne : haut {et / n:.1f} mm, bas {eb / n:.1f} mm")

    rgb = np.zeros((h, w, 3), np.uint8)
    rgb[A] = [255, 70, 70]
    rgb[B] = [70, 130, 255]
    rgb[A & B] = [245, 245, 245]
    out = HERE / "refcheck_overlay.png"
    Image.fromarray(rgb).save(out)
    print(f"overlay -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
