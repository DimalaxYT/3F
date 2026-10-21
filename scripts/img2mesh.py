#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
img2mesh.py — pipeline Image → 3D pour 3d-forge (déterministe, zéro API).

Le module MESURE (segmentation, contour, profil de largeur, couleurs) ;
l'agent DÉCIDE (mode, proportions fines, matériaux, itérations via compare.py).

Commandes :
    python img2mesh.py analyze photo.png --out out/analyze [--tol 0.14]
    python img2mesh.py build  out/analyze/analysis.json --mode revolve \
        --height 0.35 --material plastic --color "#8b3a2a" --out out/obj

Modes de construction (depuis la silhouette mesurée) :
    revolve  objets de révolution (vases, bouteilles, échecs) — profil W(z)
    extrude  objets plats (logos, épées vues de profil, plaques) — contour exact
    loft     objets « gonflés » (section super-elliptique pilotée par W(z))

Sorties analyze : analysis.json + silhouette.png + contour.png + profile.png.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.interpolate import PchipInterpolator

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import meshkit as mk                                   # noqa: E402
plt = None  # import paresseux : voir `_plt()`


def _plt():
    """Import paresseux de matplotlib.

    La mesure (segmentation, profil W(z), IoU de `compare.py`) doit rester
    utilisable dans un conteneur sans matplotlib ; seuls les tracés PNG
    (`contour.png`, `profile.png`) en dépendent.
    """
    global plt
    if plt is None:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as _p
        plt = _p
    return plt


# --------------------------------------------------------------------------- #
# Segmentation
# --------------------------------------------------------------------------- #

def load_rgba(path):
    return np.asarray(Image.open(path).convert("RGBA")).astype(np.float32)


def segment(a, tol=0.14, min_hole_frac=0.015):
    """Silhouette booléenne (h, w) du premier plan.

    Gère les fonds transparents (canal alpha) et les fonds unis
    (couleur estimée par médiane des bords). Nettoyage morphologique,
    plus grande composante connexe, rebouchage des trous < 1.5 % d'aire.
    """
    rgb = a[..., :3] / 255.0
    alpha = a[..., 3] / 255.0
    ba = np.concatenate([alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]])
    if ba.mean() < 0.5:
        mask = alpha > 0.5
        bg = "alpha"
    else:
        br = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
        br = br[ba > 0.9]
        bgc = np.median(br, axis=0) if len(br) else np.array([1.0, 1.0, 1.0])
        dist = np.sqrt(((rgb - bgc) ** 2).sum(-1))
        mask = dist > tol
        bg = "flat:" + "#%02x%02x%02x" % tuple(int(v * 255) for v in bgc)
    mask = ndimage.binary_opening(mask, np.ones((3, 3), bool))
    mask = ndimage.binary_closing(mask, np.ones((5, 5), bool))
    lab, n = ndimage.label(mask)
    if n > 1:
        sizes = ndimage.sum(mask, lab, range(1, n + 1))
        mask = lab == (1 + int(np.argmax(sizes)))
    filled = ndimage.binary_fill_holes(mask)
    holes, hn = ndimage.label(filled & ~mask)
    for i in range(1, hn + 1):
        if (holes == i).sum() < min_hole_frac * mask.sum():
            mask |= holes == i
    return mask, bg


# --------------------------------------------------------------------------- #
# Contour + profil
# --------------------------------------------------------------------------- #

def rdp(pts, eps):
    """Douglas-Peucker sur polygone ouvert (pts inclut le point de fermeture)."""
    n = len(pts)
    keep = np.zeros(n, bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 <= i0 + 1:
            continue
        p0, p1 = pts[i0], pts[i1]
        ax, ay = p1[0] - p0[0], p1[1] - p0[1]
        L = math.hypot(ax, ay)
        seg = pts[i0 + 1:i1]
        if L < 1e-9:      # corde dégénérée (polygone fermé) : distance à p0
            d = np.hypot(seg[:, 0] - p0[0], seg[:, 1] - p0[1])
        else:
            d = np.abs(ax * (seg[:, 1] - p0[1]) - ay * (seg[:, 0] - p0[0])) / L
        j = int(np.argmax(d))
        if d[j] > eps:
            k = i0 + 1 + j
            keep[k] = True
            stack.append((i0, k))
            stack.append((k, i1))
    return pts[keep]


def _contour_segments(mask):
    p = _plt()
    m = np.pad(mask.astype(float), 1)
    try:
        cs = p.contour(m, levels=[0.5])
        segs = list(cs.allsegs[0])
    except AttributeError:                     # vieilles API collections
        cs = p.contour(m, levels=[0.5])
        segs = [pp.vertices for pp in cs.collections[0].get_paths()]
    finally:
        p.close("all")
    return segs


def trace_contour(mask, max_pts=200):
    """Contour fermé ordonné (N, 2) en pixels image (y vers le bas)."""
    segs = _contour_segments(mask)
    pts = np.asarray(max(segs, key=len), float)
    if np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    c = pts.mean(0)                            # coupe au point le plus saillant
    k = int(np.argmax(((pts - c) ** 2).sum(1)))
    pts = np.roll(pts, -k, axis=0)
    closed = np.vstack([pts, pts[:1]])
    d2 = np.diff(closed, axis=0)
    per = float(np.hypot(d2[:, 0], d2[:, 1]).sum())
    eps = max(0.002 * per, 1e-3)
    for _ in range(10):
        simp = rdp(closed, eps)
        if len(simp) <= max_pts:
            break
        eps *= 1.6
    return simp[:-1] if len(simp) > 1 and np.allclose(simp[0], simp[-1]) else simp


def width_profile(mask, rows=48):
    """Profil de largeur par ligne, en unités u = hauteur de la bbox.

    Lignes [z, x0u, x1u, wu, cu] :
      z   0 (bas) → 1 (haut)
      x0u/x1u  étendue horizontale de la ligne (en u, origine = centre bbox)
      wu  largeur (u) ; cu décentrage du centre de ligne (u)
    """
    ys, xs = np.where(mask)
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    Hpx = float(max(1, y1 - y0 + 1))
    cx = (x0 + x1) / 2.0
    prof = []
    for i in range(rows):
        z = i / (rows - 1)
        yy = int(round(y1 - z * (y1 - y0)))
        sel = np.where(mask[yy, x0:x1 + 1])[0]
        if len(sel) == 0:
            prof.append([round(z, 4), 0.0, 0.0, 0.0, 0.0])
            continue
        xm0, xm1 = float(sel[0]), float(sel[-1])
        prof.append([round(z, 4),
                     round((xm0 + x0 - cx) / Hpx, 4),
                     round((xm1 + x0 - cx) / Hpx, 4),
                     round((xm1 - xm0 + 1) / Hpx, 4),
                     round(((xm0 + xm1) / 2 + x0 - cx) / Hpx, 4)])
    return prof


def symmetry_dev(prof):
    """Écart moyen des centres de ligne au centre global (0 = révolvable)."""
    d = [abs(p[4]) / max(p[3] * 0.5, 1e-6) for p in prof if p[3] > 1e-6]
    return round(float(np.mean(d)), 4) if d else 0.0


# --------------------------------------------------------------------------- #
# Couleurs
# --------------------------------------------------------------------------- #

def dominant_colors(a, mask, k=5):
    px = a[mask][:, :3]
    if len(px) > 24000:
        px = px[np.random.RandomState(0).choice(len(px), 24000, replace=False)]
    rs = np.random.RandomState(1)
    c = px[rs.choice(len(px), k, replace=False)].astype(float)
    lab = np.zeros(len(px), int)
    for _ in range(12):
        d = ((px[:, None, :].astype(float) - c[None]) ** 2).sum(-1)
        lab = d.argmin(1)
        for j in range(k):
            if (lab == j).any():
                c[j] = px[lab == j].astype(float).mean(0)
    order = np.argsort([-(lab == j).sum() for j in range(k)])
    return [{"hex": "#%02x%02x%02x" % tuple(int(round(v)) for v in c[j]),
             "frac": round(float((lab == j).sum()) / len(lab), 3)}
            for j in order]


_PRESETS = {"rubber": (0.12, 0.12, 0.12), "steel": (0.62, 0.64, 0.67),
            "aluminum": (0.74, 0.76, 0.78), "brass": (0.72, 0.58, 0.25),
            "plastic": (0.85, 0.85, 0.82), "wood": (0.55, 0.36, 0.18),
            "fabric": (0.30, 0.44, 0.65), "glass": (0.82, 0.92, 0.94)}


def material_hint(hexcol):
    r, g, b = (int(hexcol[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    mx, mn = max(r, g, b), min(r, g, b)
    sat = 0.0 if mx == 0 else (mx - mn) / mx
    if mx < 0.22 and sat < 0.35:
        return "rubber"
    if sat < 0.10 and mx > 0.55:
        return "aluminum"
    if sat < 0.12:
        return "steel"
    best, bd = "plastic", 9.0
    for name, (pr, pg, pb) in _PRESETS.items():
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if d < bd:
            best, bd = name, d
    return best


# --------------------------------------------------------------------------- #
# analyze — mesure complète d'une image
# --------------------------------------------------------------------------- #

def analyze_file(path, outdir, tol=0.14, rows=48, colors=5, max_contour=200):
    a = load_rgba(path)
    mask, bg = segment(a, tol=tol)
    if mask.sum() < 50:
        raise SystemExit("segmentation quasi vide — vérifie le fond ou --tol")
    ys, xs = np.where(mask)
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    W, H = x1 - x0 + 1, y1 - y0 + 1

    cont = trace_contour(mask, max_pts=max_contour)
    cn = [[round(float(px - x0) / W, 4), round(float(y1 - py) / H, 4)]
          for px, py in cont]                   # x∈[0,1] → droite ; y∈[0,1] → haut
    prof = width_profile(mask, rows=rows)
    sym = symmetry_dev(prof)
    fill = float(mask.sum()) / (W * H)
    cols = dominant_colors(a, mask, k=colors)
    sug = ("revolve" if (sym < 0.08 and fill > 0.45)
           else "extrude" if fill > 0.75 else "loft")

    os.makedirs(outdir, exist_ok=True)
    crop = a[y0:y1 + 1, x0:x1 + 1].astype(np.uint8)
    Image.fromarray(crop[..., :3]).save(os.path.join(outdir, "crop.png"))
    Image.fromarray((mask * 255).astype(np.uint8)).save(
        os.path.join(outdir, "silhouette.png"))

    ov = (crop[..., :3].copy() * 0.45).astype(np.uint8)   # contour rouge
    for px, py in cont:
        xx, yy = int(px - x0), int(py - y0)
        if 0 <= yy < ov.shape[0] and 0 <= xx < ov.shape[1]:
            ov[yy, xx] = (255, 40, 40)
    Image.fromarray(ov).save(os.path.join(outdir, "contour.png"))

    p = _plt()
    fig, ax = p.subplots(1, 2, figsize=(8, 3.4), constrained_layout=True)
    P = np.asarray(prof, float)
    ax[0].plot(P[:, 3] / 2, P[:, 0], lw=2, color="#d95f02")
    ax[0].plot(-P[:, 3] / 2, P[:, 0], lw=2, color="#d95f02")
    ax[0].set_title("Demi-largeurs r(z)", fontsize=9)
    ax[0].set_xlabel("u (× hauteur)", fontsize=8)
    ax[0].set_ylabel("z (bas→haut)", fontsize=8)
    ax[1].plot(P[:, 4], P[:, 0], lw=2, color="#1b9e77")
    ax[1].set_title("Décentrage centre c(z)", fontsize=9)
    ax[1].set_xlabel("u (× hauteur)", fontsize=8)
    for a_ in ax:
        a_.grid(alpha=0.3)
        a_.invert_yaxis()
    fig.savefig(os.path.join(outdir, "profile.png"), dpi=110)
    p.close(fig)

    an = {"source": os.path.basename(path), "background": bg,
          "image_size": [int(a.shape[1]), int(a.shape[0])],
          "bbox": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
          "bbox_aspect": round(W / H, 4),
          "fill_ratio": round(fill, 4),
          "symmetry_dev": sym,
          "suggested_mode": sug,
          "colors": cols,
          "material_hint": material_hint(cols[0]["hex"]),
          "units": ("contour normalisé bbox (x droite, y haut) ; profil en u = "
                    "hauteur bbox : ligne [z, x0u, x1u, wu, cu]"),
          "contour": cn,
          "width_profile": prof}
    with open(os.path.join(outdir, "analysis.json"), "w") as f:
        json.dump(an, f, indent=1)
    print(json.dumps({k: an[k] for k in
                      ("source", "background", "bbox_aspect", "fill_ratio",
                       "symmetry_dev", "suggested_mode", "colors",
                       "material_hint")}, ensure_ascii=False, indent=1))
    return an


# --------------------------------------------------------------------------- #
# build — reconstruction géométrique
# --------------------------------------------------------------------------- #

def _smooth(v, k):
    return ndimage.uniform_filter1d(np.asarray(v, float), k, mode="nearest") \
        if k > 1 else np.asarray(v, float)


def build_revolve(an, height, sections=64, smooth=3):
    z, _, _, wu, _ = (np.asarray(an["width_profile"], float).T)
    r = _smooth(0.5 * wu, smooth)
    zz = np.linspace(0.0, 1.0, 240)
    rr = np.clip(PchipInterpolator(z, np.clip(r, 0.0, None))(zz), 0.0, None)
    prof = [(float(x) * height, float(y) * height) for y, x in zip(zz, rr)]
    return mk.lathe(prof, sections=sections)


def build_extrude(an, height, depth):
    aw = float(an["bbox_aspect"])
    cont = np.asarray(an["contour"], float)
    pts = [((x - 0.5) * aw * height, y * height) for x, y in cont]
    m = mk.extrude(pts, depth)          # XY = (x_monde, z_monde), extrusion +Z
    mk.rot_x(m, 90)                     # → (x, -profondeur, z_monde)
    mk.place(m, 0, depth / 2, 0)
    return m


def build_loft(an, height, depth=0.5, roundness=0.55, square=2.4,
               sections=48, smooth=3):
    """Generalized cylinder : anneaux super-elliptiques empilés le long de Z.

    depth      : profondeur max (m) ; roundness : b(y) = roundness·a(y) (borné)
    square     : exposant super-ellipse (2 = ellipse, 4 = section « carrée »)
    """
    aw = float(an["bbox_aspect"])
    z, _, _, wu, cu = (np.asarray(an["width_profile"], float).T)
    a = _smooth(0.5 * wu, smooth)
    c = _smooth(cu, smooth)
    b = np.minimum(roundness * a, depth / (2.0 * height))
    e = 2.0 / float(square)
    th = np.linspace(0.0, 2.0 * np.pi, sections, endpoint=False)
    fx = np.sign(np.cos(th)) * np.abs(np.cos(th)) ** e
    fy = np.sign(np.sin(th)) * np.abs(np.sin(th)) ** e

    rings = []
    for i in range(len(z)):
        ai, bi, ci = max(a[i], 1e-3), max(b[i], 1e-3), c[i]
        rings.append(np.stack([(ci + ai * fx) * height,
                               bi * fy * height,
                               np.full(sections, z[i] * height)], axis=1))
    V = np.concatenate(rings, axis=0)
    S, R = sections, len(z)
    F = []
    for i in range(R - 1):
        for j in range(S):
            j2 = (j + 1) % S
            v0, v1 = i * S + j, i * S + j2
            v2, v3 = (i + 1) * S + j2, (i + 1) * S + j
            F.append([v0, v1, v2])
            F.append([v0, v2, v3])
    # refermeture : sommet central + éventail en bas et en haut
    for i in (0, R - 1):
        cidx = len(V)
        V = np.vstack([V, [[c[i] * height, 0.0, z[i] * height]]])
        for j in range(S):
            j2 = (j + 1) % S
            if i == 0:
                F.append([cidx, (i + 1) * S + j2 - S, (i + 1) * S + j - S])
            else:
                F.append([cidx, i * S + j, i * S + j2])
    import trimesh
    m = trimesh.Trimesh(V, F, process=True)
    trimesh.repair.fix_normals(m, multibody=False)
    return m


ROUGH_DEFAULT = {"plastic": 0.35, "wood": 0.55, "metal": 0.30,
                 "glass": 0.05, "fabric": 0.85, "rubber": 0.90}


def make_material(kind, color, roughness=None):
    roughness = ROUGH_DEFAULT.get(kind, 0.4) if roughness is None else roughness
    if kind == "glass":
        return mk.mat.glass(color, 0.35, roughness)
    return {"plastic": mk.mat.plastic, "wood": mk.mat.wood,
            "metal": mk.mat.metal, "fabric": mk.mat.fabric,
            "rubber": mk.mat.rubber}[kind](color, roughness)


def cmd_build(args):
    with open(args.analysis) as f:
        an = json.load(f)
    mode = args.mode or an.get("suggested_mode", "loft")
    if mode == "revolve":
        mesh = build_revolve(an, args.height, sections=args.sections,
                             smooth=args.smooth)
    elif mode == "extrude":
        mesh = build_extrude(an, args.height, depth=args.depth)
    else:
        mesh = build_loft(an, args.height, depth=args.depth,
                          roundness=args.roundness, square=args.square,
                          sections=args.sections, smooth=args.smooth)
    b = mk.Builder(args.name or "img2mesh", {"mode": mode,
                                             "height": args.height})
    b.add(mesh, make_material(args.material, args.color, args.roughness),
          name="body")
    os.makedirs(args.out, exist_ok=True)
    scene = b.scene()
    outs = []
    if "glb" in args.formats:
        p = os.path.join(args.out, f"{b.name}.glb")
        scene.export(p)
        outs.append(p)
    if "obj" in args.formats:
        outs.append(mk.export_obj_with_mtl(scene,
                    os.path.join(args.out, f"{b.name}.obj")))
    if "stl" in args.formats:
        p = os.path.join(args.out, f"{b.name}.stl")
        b.union_solid().export(p)
        outs.append(p)
    if not args.no_render:
        import renderer
        renderer.render_views(scene, args.out, b.name,
                              views=["three_quarter", "side"], size=args.size)
    print(json.dumps({"mode": mode, "out": args.out,
                      "stats": b.stats(), "files": outs}, ensure_ascii=False,
                     indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser(description="3d-forge image→3D")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("analyze", help="photo → mesures + analysis.json")
    pa.add_argument("image")
    pa.add_argument("--out", default="out/analyze")
    pa.add_argument("--tol", type=float, default=0.14,
                    help="seuil de fond (distance RGB relative)")
    pa.add_argument("--rows", type=int, default=48)
    pa.add_argument("--colors", type=int, default=5)
    pa.add_argument("--max-contour", type=int, default=200)
    pa.set_defaults(fn=None)

    pb = sub.add_parser("build", help="analysis.json → mesh étanche")
    pb.add_argument("analysis")
    pb.add_argument("--mode", choices=["revolve", "extrude", "loft"])
    pb.add_argument("--height", type=float, default=0.30,
                    help="hauteur cible en mètres")
    pb.add_argument("--depth", type=float, default=0.12,
                    help="profondeur (extrude/loft)")
    pb.add_argument("--roundness", type=float, default=0.55)
    pb.add_argument("--square", type=float, default=2.4)
    pb.add_argument("--sections", type=int, default=48)
    pb.add_argument("--smooth", type=int, default=3)
    pb.add_argument("--material", default="plastic",
                    choices=list(ROUGH_DEFAULT))
    pb.add_argument("--color", default="#8b3a2a")
    pb.add_argument("--roughness", type=float, default=None)
    pb.add_argument("--name", default=None)
    pb.add_argument("--out", default="out/img2mesh")
    pb.add_argument("--formats", nargs="*", default=["glb", "obj"])
    pb.add_argument("--size", type=int, default=768)
    pb.add_argument("--no-render", action="store_true")
    pb.set_defaults(fn=cmd_build)

    args = ap.parse_args(argv)
    if args.cmd == "analyze":
        cmd_analyze_impl(args)
    else:
        args.fn(args)


def cmd_analyze_impl(args):
    analyze_file(args.image, args.out, tol=args.tol, rows=args.rows,
                 colors=args.colors, max_contour=args.max_contour)


if __name__ == "__main__":
    main()
