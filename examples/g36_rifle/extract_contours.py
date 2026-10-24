#!/usr/bin/env python3
"""Extrait les contours RÉELS du G36 depuis la photo de référence.

    PYTHONPATH=scripts python3 examples/g36_rifle/extract_contours.py

Sort un bloc Python `PROFILES = {...}` prêt à coller dans `build_g36.py`.
Chaque profil est en millimètres : y = 0 au milieu de l'arme (+ vers la bouche),
z = 0 sur l'axe du canon (+ vers le haut).

Unités et repère viennent du dépouillement : L = 998 mm sur 1276 px,
axe du canon à la ligne 103,5 de la vue recadrée.

Le masque inclut le chargeur **translucide** de la référence (seuil sombre OU
couleur) : il fait partie de la silhouette, un seuil de luminance l'oublierait.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

REF = ROOT / "image-search" / "g36-official-left-profile-rails.png"
REF_BOX = (198, 92, 1474, 449)
MM = 998.0


def mask(fill: bool = True) -> np.ndarray:
    """Masque de l'arme. `fill=False` garde les lumières (fenêtres) ouvertes."""
    im = Image.open(REF).convert("RGB").crop(REF_BOX)
    a = np.asarray(im).astype(int)
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1)
    m = (mx < 185) | (sat > 0.05)
    m = ndi.binary_closing(m, np.ones((3, 3)))
    if fill:
        m = ndi.binary_fill_holes(m)
    lab, n = ndi.label(m)
    sizes = ndi.sum(m, lab, range(1, n + 1))
    k = int(np.argmax(sizes)) + 1
    m = lab == k
    return ndi.binary_fill_holes(m) if fill else m


def smooth(v: np.ndarray, k: int = 9) -> np.ndarray:
    """Médiane glissante : tue le bruit JPEG sans arrondir les arêtes franches."""
    out = v.copy()
    h = k // 2
    for i in range(len(v)):
        w = v[max(0, i - h):i + h + 1]
        w = w[~np.isnan(w)]
        if len(w):
            out[i] = np.median(w)
    return out


def rdp(p: np.ndarray, eps: float) -> np.ndarray:
    if len(p) < 3:
        return p
    a, b = p[0], p[-1]
    ab = b - a
    L = np.linalg.norm(ab)
    d = (np.abs(np.cross(ab, p - a)) / L) if L > 0 else np.linalg.norm(p - a, axis=1)
    i = int(np.argmax(d))
    if d[i] > eps:
        return np.vstack([rdp(p[:i + 1], eps)[:-1], rdp(p[i:], eps)])
    return np.array([a, b])


def main() -> int:
    m = mask()
    H, W = m.shape
    S = MM / W
    seg = m[:, int(0.02 * W):int(0.12 * W)]
    AX = np.where(seg.any(axis=1))[0].mean()
    print(f"# échelle {S:.4f} mm/px, axe canon ligne {AX:.2f}", file=sys.stderr)

    def Y(x):
        return (0.5 - x / (W - 1)) * MM

    def Z(y):
        return (AX - y) * S

    top = np.full(W, np.nan)
    bot = np.full(W, np.nan)
    for x in range(W):
        c = np.where(m[:, x])[0]
        if len(c):
            top[x], bot[x] = Z(c.min()), Z(c.max())
    top, bot = smooth(top), smooth(bot)

    # trous intérieurs : fenêtre d'arche, fenêtre de crosse
    # trous : on repart du masque NON bouché, sinon il n'y a plus rien à trouver
    bg = ~mask(fill=False)
    lab, n = ndi.label(bg)
    border = set(lab[0, :]) | set(lab[-1, :]) | set(lab[:, 0]) | set(lab[:, -1])
    holes = []
    for k in range(1, n + 1):
        if k in border:
            continue
        reg = lab == k
        if reg.sum() < 1500:
            continue
        yy, xx = np.where(reg)
        holes.append((xx.mean(), (Y(xx.min()), Y(xx.max())), (Z(yy.min()), Z(yy.max())), int(reg.sum())))
    holes.sort(key=lambda h: h[0])

    out = ["PROFILES = {"]
    out.append("    # (y_min, y_max, [(y, z)...] contour haut, [(y, z)...] contour bas)")
    for name, y_hi, y_lo in (("body", 318.0, -260.0), ("stock", -260.0, -499.0)):
        xs = np.where((np.nan_to_num(top) != 0) & (bot == bot))[0]
        sel = [x for x in xs if y_lo - 1e-9 <= Y(x) <= y_hi + 1e-9]
        if not sel:
            continue
        sel = sorted(sel, key=lambda x: -Y(x))       # de l'avant vers l'arrière
        pts_t = np.array([[Y(x), top[x]] for x in sel])
        pts_b = np.array([[Y(x), bot[x]] for x in sel])
        st = rdp(pts_t, float(__import__("os").environ.get("EPS","3.5")))
        sb = rdp(pts_b, float(__import__("os").environ.get("EPS","3.5")))
        out.append(f"    {name!r}: (")
        out.append("        [")
        for y, z in st:
            out.append(f"            ({y / 1000:+.4f}, {z / 1000:+.4f}),")
        out.append("        ],")
        out.append("        [")
        for y, z in sb[::-1]:
            out.append(f"            ({y / 1000:+.4f}, {z / 1000:+.4f}),")
        out.append("        ],")
        out.append("    ),")

    out.append("    'holes': [")
    for _, (ya, yb), (za, zb), area in holes:
        if abs(yb - ya) < 15:
            continue
        out.append(f"        # {abs(yb - ya):.0f} x {abs(zb - za):.0f} mm ({area} px)")
        out.append(f"        ({ya / 1000:+.4f}, {zb / 1000:+.4f}, {yb / 1000:+.4f}, {za / 1000:+.4f}),")
    out.append("    ],")
    out.append("}")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
