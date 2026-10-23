#!/usr/bin/env python3
"""
texture_4k.py — Moteur de texture 4K (`4096²`) sculpté, projeté et vérifiable.

Pourquoi ce module existe
-------------------------
Les cartes `1024²` du pipeline game-ready donnaient ~8 pixels par écaille : le
maillage était bon mais la surface se lisait « plastique lisse », sans le
micro-relief que l'œil attend sur une créature sculptée. Un simple upscale
`1024 -> 4096` n'ajoute rien (aucun signal nouveau) : il faut **recalculer**
la surface à la résolution cible.

Ce que fait `synthesize_4k_maps`
-------------------------------
1. **Rastérisation UV par bandes** (512 lignes) des géométries du `.glb` :
   chaque texel 4K reçoit sa **position monde** et sa **normale monde** exactes
   (aucune boucle Python pixel par pixel : vecteurs NumPy par triangle).
2. **Projection photo 4K** : le même modèle caméra Z-buffer que
   `photo_to_3d.project_photo_pbr` (symétrie `(|x|, y, z)` continue), mais
   appliqué à 4096² : les écailles et les nervures de la photo sont enfin
   résolues, pas interpolées.
3. **Micro-relief analytique monde** (indépendant de l'UV, donc sans étirement) :
   - `scales` : losanges imbriqués type varan avec lèvre d'imbrication + teinte
     par écaille (hash déterministe),
   - `wrinkles` : plis de membrane / rides de peau à haute fréquence,
   - `keratin` : anneaux de croissance des cornes, griffes et crocs.
   Chaque champ alimente l'albédo (creux sombres, crêtes claires), la **normale
   tangentielle** (gradient réel du champ) et l'**ORM** (AO de cavité + rugosité).
4. Écrit `render_4k/` (BC, N DirectX, N OpenGL, ORM, AO, Cavity, MatID) et
   patchte les `.glb` **en place** sans jamais perdre `UCX_*` ni `Idle_Action`.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
import trimesh

import photo_to_3d as p2d
import renderer as rn


# --------------------------------------------------------------------------- #
# 1. Rastérisation UV par bandes : position + normale monde par texel
# --------------------------------------------------------------------------- #

def _iter_uv_bands(
    verts_w: np.ndarray,
    faces: np.ndarray,
    uv: np.ndarray,
    nrm_w: np.ndarray,
    S: int,
    band: int = 512,
    vattr: np.ndarray | None = None,
):
    """Génère `(y0, y1, pos, nrm, valid)` par bandes de lignes de l'atlas UV.

    `pos` a la forme `(y1 - y0, S, 3)` (float32) : position monde exacte du texel.
    Les triangles sont dilatés de `-0.02` en poids barycentrique pour couvrir
    100 % des bords d'îlots UV (aucune couture au mipmapping).
    """
    tri = uv[faces]                              # (F, 3, 2)
    tx = tri[..., 0] * S
    ty = (1.0 - tri[..., 1]) * S                 # ligne 0 = v = 1
    minx, maxx = tx.min(1), tx.max(1)
    miny, maxy = ty.min(1), ty.max(1)

    for y0 in range(0, S, band):
        y1 = min(y0 + band, S)
        sel = np.flatnonzero(
            (maxy >= y0 - 1.0) & (miny <= y1 + 1.0) & (maxx >= 0.0) & (minx <= S - 1)
        )
        pos = np.zeros((y1 - y0, S, 3), dtype=np.float32)
        nrm = np.zeros((y1 - y0, S, 3), dtype=np.float32)
        attr = np.zeros((y1 - y0, S, 3), dtype=np.float32) if vattr is not None else None
        ok = np.zeros((y1 - y0, S), dtype=bool)
        for t in sel:
            ia, ib, ic = faces[t]
            ax, bx, cx = tx[t]
            ay, by, cy = ty[t]
            den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(den) < 1e-12:
                continue
            xa = max(int(math.floor(min(ax, bx, cx))) - 1, 0)
            xb = min(int(math.ceil(max(ax, bx, cx))) + 1, S - 1)
            ya = max(int(math.floor(min(ay, by, cy))) - 1, y0)
            yb = min(int(math.ceil(max(ay, by, cy))) + 1, y1 - 1)
            if xb < xa or yb < ya:
                continue
            # Les îlots UV sont des bandes FINES : un seul échantillon au centre du
            # texel rate l'intérieur des triangles allongés (`~1 texel/triangle`
            # mesuré à 512 -> atlas criblé de trous). On suréchantillonne 2x2 pour
            # une couverture raster correcte.
            sub = 2
            offs = (np.arange(sub, dtype=np.float64) + 0.5) / sub - 0.5
            gx0, gy0 = np.meshgrid(
                np.arange(xa, xb + 1, dtype=np.float64),
                np.arange(ya, yb + 1, dtype=np.float64),
            )
            inv = 1.0 / den
            hit = np.zeros(gx0.shape, dtype=bool)
            w_acc = np.zeros(gx0.shape + (3,), dtype=np.float64)
            cnt_acc = np.zeros(gx0.shape, dtype=np.float64)
            for oy in offs:
                for ox in offs:
                    gx = gx0 + 0.5 + ox
                    gy = gy0 + 0.5 + oy
                    w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) * inv
                    w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) * inv
                    w2 = 1.0 - w0 - w1
                    ins = (w0 >= -0.02) & (w1 >= -0.02) & (w2 >= -0.02)
                    if ins.any():
                        hit |= ins
                        w_acc[..., 0] += np.where(ins, w0, 0.0)
                        w_acc[..., 1] += np.where(ins, w1, 0.0)
                        w_acc[..., 2] += np.where(ins, w2, 0.0)
                        cnt_acc += ins
            if not hit.any():
                continue
            # `np.nonzero` renvoie des indices LOCAUX à la fenêtre du triangle :
            # il faut ré-ancrer sur l'atlas (xa / ya), sinon tous les triangles
            # peignent dans les ~30 premières colonnes (couverture 4 %).
            ly, lx = np.nonzero(hit)          # indices LOCAUX à la fenêtre du triangle
            ry = ly + (ya - y0)               # ligne locale à la bande
            rx = lx + xa                      # colonne absolue dans l'atlas
            n_hit = np.maximum(cnt_acc[ly, lx], 1.0)
            v0 = np.clip(w_acc[ly, lx, 0] / n_hit, 0.0, 1.0)
            v1 = np.clip(w_acc[ly, lx, 1] / n_hit, 0.0, 1.0)
            v2 = np.clip(w_acc[ly, lx, 2] / n_hit, 0.0, 1.0)
            vs = np.maximum(v0 + v1 + v2, 1e-8)
            v0, v1, v2 = v0 / vs, v1 / vs, v2 / vs
            sub_p = v0[:, None] * verts_w[ia] + v1[:, None] * verts_w[ib] + v2[:, None] * verts_w[ic]
            sub_n = v0[:, None] * nrm_w[ia] + v1[:, None] * nrm_w[ib] + v2[:, None] * nrm_w[ic]
            ln = np.maximum(np.linalg.norm(sub_n, axis=1, keepdims=True), 1e-8)
            pos[ry, rx] = sub_p.astype(np.float32)
            nrm[ry, rx] = (sub_n / ln).astype(np.float32)
            if attr is not None:
                sub_a = v0[:, None] * vattr[ia] + v1[:, None] * vattr[ib] + v2[:, None] * vattr[ic]
                attr[ry, rx] = sub_a.astype(np.float32)
            ok[ry, rx] = True

        yield y0, y1, pos, nrm, ok, attr


# --------------------------------------------------------------------------- #
# 2. Champs de micro-relief analytiques en espace MONDE
# --------------------------------------------------------------------------- #

def _hash01(a: np.ndarray, b: np.ndarray, seed: int = 0) -> np.ndarray:
    h = np.sin(a * 127.1 + b * 311.7 + seed * 74.7) * 43758.5453
    return h - np.floor(h)


def _triplanar_pair(p: np.ndarray, n: np.ndarray):
    """Coordonnées 2D triplanaires pondérées par la normale : zéro couture, zéro étirement."""
    an = np.abs(n)
    w = an / np.maximum(an.sum(axis=1, keepdims=True), 1e-6)
    return (
        (p[:, 1], p[:, 2], w[:, 0]),
        (p[:, 0], p[:, 2], w[:, 1]),
        (p[:, 0], p[:, 1], w[:, 2]),
    )


def scale_field(
    p: np.ndarray,
    n: np.ndarray,
    size: float = 0.0072,
    sharpness: float = 1.55,
) -> dict:
    """Écailles losangiques imbriquées (type varan/dragon) en espace monde.

    Retourne `height` (bombé + lèvre d'imbrication, ~[-0.4, 1]), `seam`
    (sillon inter-écailles, [0, 1]) et `tint` (variation par écaille, ±1).
    """
    freq = 1.0 / max(float(size), 1e-6)

    def _one(u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        # Domain warp : casse l'alignement régulier (sinon on lit des rayures, pas des écailles)
        u = u + 0.0042 * np.sin(v * 143.0 + u * 61.0) + 0.0021 * np.sin(v * 377.0)
        v = v + 0.0038 * np.sin(u * 131.0 - v * 47.0) + 0.0019 * np.sin(u * 349.0)
        row = v * freq * 1.1547
        row_i = np.floor(row)
        off = 0.5 * np.mod(row_i, 2.0)
        fu = u * freq + off
        col_i = np.floor(fu)
        du = np.mod(fu, 1.0) - 0.5
        dv = np.mod(row, 1.0) - 0.5
        # Losange asymétrique : pointe basse = lèvre d'imbrication
        d = np.sqrt((du * 1.16) ** 2 + ((dv + 0.12) * 1.04) ** 2)
        dome = np.clip(1.0 - (d / 0.60) ** float(sharpness), -0.40, 1.0)
        lip = 0.30 * np.exp(-(((dv - 0.33) / 0.13) ** 2)) * np.clip(1.0 - np.abs(du) * 2.0, 0.0, 1.0)
        seam = np.clip((d - 0.44) / 0.16, 0.0, 1.0)
        tint = _hash01(col_i, row_i, seed=3)[..., ] * 2.0 - 1.0
        return dome + lip, seam, tint

    h = np.zeros(len(p), dtype=np.float32)
    s = np.zeros(len(p), dtype=np.float32)
    t = np.zeros(len(p), dtype=np.float32)
    for u_c, v_c, w_c in _triplanar_pair(p, n):
        hh, ss, tt = _one(u_c, v_c)
        h += w_c * hh
        s += w_c * ss
        t += w_c * tt
    return {"height": h, "seam": s, "tint": t}


def scute_field(p: np.ndarray, n: np.ndarray, pitch: float = 0.021) -> dict:
    """Plaques ventrales transversales (scutes) : le ventre d'un dragon n'est pas
    couvert de petites écailles mais de larges plaques bombées séparées par un sillon.
    """
    z = p[:, 2]
    row = z / max(pitch, 1e-6)
    ri = np.floor(row)
    fz = np.mod(row, 1.0)
    dome = np.clip(1.0 - ((fz - 0.5) / 0.44) ** 2, 0.0, 1.0)
    seam = np.clip((np.abs(fz - 0.5) - 0.36) / 0.12, 0.0, 1.0)
    tint = _hash01(ri, np.zeros_like(ri), seed=11) * 2.0 - 1.0
    # Bord latéral : les scutes s'arrondissent sur les flancs.
    side = np.clip(1.0 - np.abs(n[:, 1]) * 0.35, 0.0, 1.0)
    return {
        "height": ((0.85 * dome - 0.16) * side).astype(np.float32),
        "seam": (seam * side).astype(np.float32),
        "tint": (tint * 0.55).astype(np.float32),
    }


def wrinkle_field(p: np.ndarray, n: np.ndarray, freq: float = 210.0) -> dict:
    """Micro-plis organiques (membranes d'ailes, peau entre les plaques, gencives)."""
    h = np.zeros(len(p), dtype=np.float32)
    for u_c, v_c, w_c in _triplanar_pair(p, n):
        r1 = np.sin(u_c * freq + np.sin(v_c * freq * 0.62) * 1.9)
        r2 = np.sin(v_c * freq * 1.37 + np.sin(u_c * freq * 0.41) * 2.4)
        fine = np.sin((u_c + v_c) * freq * 2.9) * 0.35
        h += w_c * (0.55 * r1 + 0.45 * r2 + fine)
    h *= 0.5
    return {"height": h.astype(np.float32), "seam": np.clip(-h, 0.0, 1.0).astype(np.float32)}


def keratin_field(p: np.ndarray, n: np.ndarray) -> dict:
    """Anneaux de croissance transversaux des cornes, griffes et crocs."""
    axis = np.array([0.0, 0.35, 1.0], dtype=np.float32)
    axis /= np.linalg.norm(axis)
    along = p @ axis
    rings = 0.5 + 0.5 * np.sin(along * 165.0 + 0.8 * np.sin(along * 41.0))
    groove = np.clip((0.45 - np.abs(rings - 0.5) * 2.0) * 2.0, 0.0, 1.0)
    return {
        "height": ((rings - 0.5) * 1.2).astype(np.float32),
        "seam": (1.0 - groove * 0.75).astype(np.float32),
    }


def _height_to_normal_tangent(h: np.ndarray, strength: float) -> tuple[np.ndarray, np.ndarray]:
    """Gradient du champ de hauteur en espace UV -> perturbation tangentielle (dx, dy)."""
    dhu = np.gradient(h, axis=1)
    dhv = np.gradient(h, axis=0)
    return -dhu * strength, dhv * strength


def _flat_fill(arr: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Prolonge les texels valides dans les marges d'îlots UV (zéro couture, zéro bord noir)."""
    if valid.all():
        return arr
    if not valid.any():
        return arr
    _, idx = ndimage.distance_transform_edt(~valid, return_indices=True)
    return arr[idx[0], idx[1]]


# --------------------------------------------------------------------------- #
# 3. Projection photo 4K (même modèle caméra que photo_to_3d)
# --------------------------------------------------------------------------- #

def prepare_photo_camera(
    scene: trimesh.Scene,
    photo_path: str | Path,
    azimuth_deg: float = 86.0,
    elevation_deg: float = 3.5,
    fov: float = 38.0,
    cam_res: int = 1400,
) -> dict:
    """Prépare le détourage photo, la caméra et le Z-buffer de la scène complète."""
    fg = p2d.extract_clean_foreground(photo_path)
    rgb = fg["rgb"].astype(np.float32) / 255.0
    mask = fg["mask"]

    inner = ndimage.binary_erosion(mask, iterations=3)
    if inner.sum() < 200:
        inner = mask
    _, near_idx = ndimage.distance_transform_edt(~inner, return_indices=True)
    safe = rgb[near_idx[0], near_idx[1]]
    blur = ndimage.gaussian_filter(safe, sigma=(1.0, 1.0, 0.0))
    sharp = np.clip(safe + 0.35 * (safe - blur), 0.0, 1.0)

    parts = rn._gather(scene)
    all_v = np.vstack([pt[0] for pt in parts])
    lo, hi = all_v.min(0), all_v.max(0)
    center = 0.5 * (lo + hi)
    radius = float(np.linalg.norm(hi - lo) / 2.0) + 1e-6
    eye = center + radius * 3.1 * np.array([
        math.sin(math.radians(azimuth_deg)) * math.cos(math.radians(elevation_deg)),
        -math.cos(math.radians(azimuth_deg)) * math.cos(math.radians(elevation_deg)),
        math.sin(math.radians(elevation_deg)),
    ])
    PV = rn._perspective(fov, 1.0, radius * 0.1, radius * 12.0) @ rn._look_at(eye, center)
    view_dir = (eye - center) / max(float(np.linalg.norm(eye - center)), 1e-9)

    zbuf = np.full((cam_res, cam_res), np.inf, dtype=np.float64)
    for pt in parts:
        v_w, f_w = pt[0], pt[2]
        hom = np.column_stack([v_w, np.ones(len(v_w))]) @ PV.T
        wc = np.maximum(hom[:, 3], 1e-6)
        px = (hom[:, 0] / wc * 0.5 + 0.5) * cam_res
        py = (0.5 - hom[:, 1] / wc * 0.5) * cam_res
        rn._rasterize_part(px, py, wc, hom[:, 3] > 1e-4, f_w, cam_res, cam_res, zbuf, update_z=True)

    # Recadre la photo sur la silhouette pour un mapping identité (aucune déformation harmonique)
    _, mask_ren = rn.render_view(
        scene, azimuth_deg=azimuth_deg, elevation_deg=elevation_deg,
        size=cam_res, fov=fov, ssaa=1, shadow=False, post=False, return_mask=True,
    )
    m3 = np.asarray(mask_ren) > 127
    ys3, xs3 = np.where(m3)
    xp0, yp0, xp1, yp1 = fg["bbox"]

    return {
        "fg": fg, "photo": sharp, "mask": mask,
        "PV": PV, "zbuf": zbuf, "view_dir": view_dir, "radius": radius,
        "cam_res": cam_res,
        "tex_box": (float(xs3.min()), float(xs3.max()), float(ys3.min()), float(ys3.max())),
        "ph_box": (float(xp0), float(xp1), float(yp0), float(yp1)),
    }


def sample_photo(cam: dict, pos: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Projette des points monde dans la photo (symétrie `|x|`) -> `(couleur, poids)`."""
    PV = cam["PV"]
    res = cam["cam_res"]
    view_dir = cam["view_dir"]
    tx0, tx1, ty0, ty1 = cam["tex_box"]
    px0, px1, py0, py1 = cam["ph_box"]
    bw3 = max(tx1 - tx0, 1.0)
    bh3 = max(ty1 - ty0, 1.0)
    bwp = max(px1 - px0, 1.0)
    bhp = max(py1 - py0, 1.0)

    pts = np.asarray(pos, dtype=np.float64)
    sym = pts.copy()
    sym[:, 0] = np.abs(sym[:, 0]) if view_dir[0] >= 0 else -np.abs(sym[:, 0])

    def _proj(arr: np.ndarray):
        hom = np.column_stack([arr, np.ones(len(arr))]) @ PV.T
        wc = np.maximum(hom[:, 3], 1e-6)
        sx = np.clip((hom[:, 0] / wc * 0.5 + 0.5) * res, 0.0, res - 1.001)
        sy = np.clip((0.5 - hom[:, 1] / wc * 0.5) * res, 0.0, res - 1.001)
        return sx, sy, wc

    sx_d, sy_d, wc_d = _proj(pts)
    sx_s, sy_s, wc_s = _proj(sym)
    zd = cam["zbuf"][np.round(sy_d).astype(np.int64), np.round(sx_d).astype(np.int64)]
    zs = cam["zbuf"][np.round(sy_s).astype(np.int64), np.round(sx_s).astype(np.int64)]
    tol = cam["radius"] * 0.065
    vis_d = wc_d <= zd + tol
    vis_s = wc_s <= zs + tol
    near_side = (pts[:, 0] * (1.0 if view_dir[0] >= 0 else -1.0)) >= -0.004
    use_d = vis_d & near_side

    sx = np.where(use_d, sx_d, sx_s)
    sy = np.where(use_d, sy_d, sy_s)
    valid = vis_d | vis_s

    p_x = px0 + ((sx - tx0) / bw3) * bwp
    p_y = py0 + ((sy - ty0) / bh3) * bhp
    col = p2d._bilinear_sample_rgb(cam["photo"], p_x, p_y)
    return col.astype(np.float32), valid


# --------------------------------------------------------------------------- #
# 4. Synthèse des cartes 4K
# --------------------------------------------------------------------------- #

def _material_profile(name: str) -> dict:
    nm = name.lower()
    if "wing" in nm:
        return {"detail": "wing"}
    if "head" in nm:
        return {"detail": "head"}
    return {"detail": "body"}


# --------------------------------------------------------------------------- #
# 2 bis. Palette procédurale : la couleur vient de la FORME, pas d'un aplat
# --------------------------------------------------------------------------- #

# Teintes de référence mesurées sur la photo du dragon cramoisi.
PAL = {
    "dorsal":   np.array([0.360, 0.121, 0.063], dtype=np.float32),   # #5c1f10
    "flank":    np.array([0.470, 0.156, 0.078], dtype=np.float32),   # #782814
    "belly":    np.array([0.741, 0.553, 0.310], dtype=np.float32),   # #bd8d4f
    "membrane": np.array([0.560, 0.329, 0.200], dtype=np.float32),   # #8f5433
    "keratin":  np.array([0.902, 0.851, 0.741], dtype=np.float32),   # #e6d9bd
}


def _smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / max(e1 - e0, 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def palette_color(p: np.ndarray, n: np.ndarray, detail: str = "body",
                  z_range: tuple[float, float] | None = None) -> np.ndarray:
    """Couleur de base déduite de l'orientation monde + de l'altitude.

    L'atlas 1024 est un dégradé très basse fréquence (bake du voxel sculpt) : s'en
    servir seul donne des aplats « plastique » (ventre beige, flancs mauves). Ici la
    teinte est reconstruite à partir de la géométrie : dorsale sombre, flancs
    cramoisis, ventre sable, membranes brunes — puis une marbrure basse fréquence
    casse l'aplat.
    """
    up = n[:, 1]
    # Sur la tête, presque tout est cramoisi : seul le dessous de mâchoire est sable.
    if detail == "head":
        up = up + 0.34
    # ventre (normale vers le bas) -> flanc -> dos (normale vers le haut)
    t_up = _smoothstep(-0.70, 0.05, up)
    col = PAL["belly"][None, :] * (1.0 - t_up)[:, None] + PAL["flank"][None, :] * t_up[:, None]
    t_d = _smoothstep(0.40, 0.95, up)
    col = col * (1.0 - t_d)[:, None] + PAL["dorsal"][None, :] * t_d[:, None]

    if detail == "wing":
        # Membranes : brun chaud, plus clair près des nervures (z élevé).
        z = p[:, 2]
        # Plage z GLOBALE (jamais recalculée par bande : sinon marches visibles).
        z0, z1 = z_range if z_range is not None else (float(z.min()), float(z.max()))
        zr = np.clip((z - z0) / max(z1 - z0, 1e-6), 0.0, 1.0)
        mem = PAL["membrane"][None, :] * (0.88 + 0.26 * zr)[:, None]
        col = 0.30 * col + 0.70 * mem

    # Marbrure basse fréquence (monde) : ±7 %, déterministe.
    x, y, z = p[:, 0], p[:, 1], p[:, 2]
    mott = (
        np.sin(31.0 * x + 17.0 * z) * np.sin(23.0 * y - 11.0 * z)
        + 0.5 * np.sin(57.0 * z + 13.0 * x)
    )
    col = col * (1.0 + 0.07 * mott)[:, None]
    return np.clip(col, 0.0, 1.0).astype(np.float32)


def synthesize_4k_maps(
    out_dir: str | Path,
    name: str,
    photo_path: str | Path | None = None,
    tex_size: int = 4096,
    azimuth_deg: float = 86.0,
    elevation_deg: float = 3.5,
    fov: float = 38.0,
    band: int = 512,
    write_glb: bool = True,
) -> dict:
    """Génère `render_4k/` (BC / N / ORM / AO / Cavity / MatID) à `tex_size²` et patche les `.glb`.

    Traitement **par bandes de lignes** : la mémoire pic reste ~`O(band x S)` et non
    `O(S x S x canaux)`, ce qui permet de cuire du 4096² sur une machine 3 Go.
    """
    out_p = Path(out_dir)
    render_dir = out_p / "render_4k"
    render_dir.mkdir(parents=True, exist_ok=True)

    game_glb = out_p / f"{name}_game.glb"
    # Léger : la géométrie, les UV et les couleurs de sommets suffisent ; relire des
    # atlas 4096² d'un run précédent ferait un OOM inutile.
    scene = p2d.load_scene_light(game_glb, max_tex=1024)
    cam = prepare_photo_camera(scene, photo_path, azimuth_deg, elevation_deg, fov) if photo_path else None

    S = int(tex_size)
    band = int(min(max(band, 64), S))
    written: list[dict] = []
    glb_mats: list[tuple[Image.Image, Image.Image, Image.Image]] = []

    for g_name, geom in scene.geometry.items():
        vis = getattr(geom, "visual", None)
        uv = getattr(vis, "uv", None)
        mat = getattr(vis, "material", None)
        if uv is None or mat is None or getattr(mat, "baseColorTexture", None) is None:
            continue

        # Base couleur = atlas issu du bake de la sculpture (basse fréquence fiable).
        # Il est LÉGÈREMENT adouci : agrandir brutalement un 1024² fait apparaître les
        # facettes du low-poly (« triangles peints »). Le détail fin n'est pas repris
        # de l'atlas — il est RECALCULÉ en 4K (champs analytiques + projection photo).
        from PIL import ImageFilter
        bh0, bw0 = mat.baseColorTexture.size
        base_bc_img = (
            mat.baseColorTexture.convert("RGB")
            .resize((S, S), Image.Resampling.BICUBIC)
            .filter(ImageFilter.GaussianBlur(max(S / 512.0, 1.0)))
        )

        out_bc = np.zeros((S, S, 3), dtype=np.uint8)
        out_n = np.zeros((S, S, 3), dtype=np.uint8)
        out_orm = np.zeros((S, S, 3), dtype=np.uint8)
        cov = np.zeros((S, S), dtype=bool)

        tf = np.eye(4)
        for nd in scene.graph.nodes_geometry:
            m_n, g_n = scene.graph[nd]
            if g_n == g_name:
                tf = m_n
                break
        v_w = trimesh.transformations.transform_points(np.asarray(geom.vertices, dtype=np.float64), tf)
        n_w = np.asarray(geom.vertex_normals, dtype=np.float64) @ tf[:3, :3].T
        n_w /= np.maximum(np.linalg.norm(n_w, axis=1, keepdims=True), 1e-8)
        faces = np.asarray(geom.faces, dtype=np.int64)
        prof = _material_profile(g_name)
        z_range = (float(v_w[:, 2].min()), float(v_w[:, 2].max()))
        LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

        for y0, y1, pos, nrm, ok, attr in _iter_uv_bands(
                v_w, faces, np.asarray(uv), n_w, S, band=band):
            cov[y0:y1] = ok
            if not ok.any():
                continue
            p = pos[ok]
            n = nrm[ok]
            base_px = np.asarray(base_bc_img.crop((0, y0, S, y1)), dtype=np.float32).reshape(-1, 3)
            base_px = base_px.reshape(y1 - y0, S, 3)[ok] / 255.0
            # L'atlas 1024 est un dégradé basse fréquence : seul, il donne des aplats
            # « plastique ». La palette reconstruit le contraste de forme (dos sombre,
            # ventre sable, membranes brunes) : 50/50 garde la teinte photo sans aplat.
            base_px = 0.35 * base_px + 0.65 * palette_color(p, n, prof["detail"], z_range)
            lum_base = base_px @ LUMA
            sat_base = base_px.max(axis=1) - base_px.min(axis=1)

            if prof["detail"] == "wing":
                # Membranes : plis fins + gros plis -> deux octaves (le 4K doit
                # montrer des veines, pas une peau lisse).
                f1 = wrinkle_field(p, n, freq=210.0)
                f2 = wrinkle_field(p, n, freq=64.0)
                fld = {
                    "height": (0.68 * f1["height"] + 0.55 * f2["height"]).astype(np.float32),
                    "seam": (0.68 * f1["seam"] + 0.55 * f2["seam"]).astype(np.float32),
                    "tint": f1.get("tint", np.zeros(len(p), dtype=np.float32)),
                }
                amph, seam_w = 0.80, 0.55
            elif prof["detail"] == "head":
                fld = scale_field(p, n, size=0.0044, sharpness=1.7)
                amph, seam_w = 0.85, 0.80
            else:
                fld = scale_field(p, n, size=0.0078, sharpness=1.5)
                amph, seam_w = 1.0, 0.85

            # Kératine (cornes, griffes, crocs) : vraiment très claire ET désaturée.
            # Un seuil trop bas transformait des zones du ventre en taches « girafe ».
            ivory = (lum_base > 0.74) & (sat_base < 0.16)
            # Ambre = yeux/plaies luisantes, uniquement sur la tête, très saturées.
            # (Un seuil large attrapait tout le ventre sable -> relief supprimé.)
            amber = np.zeros(len(p), dtype=bool)
            if prof["detail"] == "head":
                amber = (base_px[:, 0] > 0.62) & (sat_base > 0.50) & (base_px[:, 2] < 0.30)
            h_mix, s_mix, t_mix = fld["height"], fld["seam"], fld.get("tint", np.zeros(len(p), dtype=np.float32))
            if ivory.any():
                kf = keratin_field(p, n)
                h_mix = np.where(ivory, kf["height"] * 0.8, h_mix)
                s_mix = np.where(ivory, kf["seam"], s_mix)
            if prof["detail"] != "wing":
                belly_w = _smoothstep(0.16, -0.58, n[:, 1])
                if float(belly_w.max()) > 0.05:
                    sc = scute_field(p, n)
                    h_mix = (h_mix * (1.0 - belly_w) + sc["height"] * belly_w).astype(np.float32)
                    s_mix = (s_mix * (1.0 - belly_w) + sc["seam"] * belly_w).astype(np.float32)
                    t_mix = (t_mix * (1.0 - belly_w) + sc["tint"] * belly_w).astype(np.float32)
            h_mix = np.where(amber, 0.0, h_mix).astype(np.float32)
            s_mix = np.where(amber, 0.0, s_mix).astype(np.float32)
            t_mix = np.where(amber, 0.0, t_mix).astype(np.float32)

            # Couleur locale : projection photo 4K si disponible (zones visibles seulement)
            px_col = base_px
            if cam is not None:
                photo_col, vis_p = sample_photo(cam, p)
                w_photo = np.where(vis_p, 0.78, 0.0).astype(np.float32)
                w_photo = np.where(ivory | amber, 0.0, w_photo)
                px_col = base_px * (1.0 - w_photo[:, None]) + photo_col * w_photo[:, None]

            # Courbe en S + creux d'écailles + crêtes + teinte par écaille
            lum = px_col @ LUMA
            lum_s = np.clip(0.5 + (lum - 0.5) * 1.18, 0.0, 1.0)
            gain = (lum_s / np.maximum(lum, 1e-4))[:, None]
            relief = (1.0 + 0.30 * amph * h_mix)[:, None]
            groove = (1.0 - 0.52 * seam_w * s_mix)[:, None]
            tint = (1.0 + 0.13 * t_mix)[:, None]
            bc_px = np.clip(px_col * gain * relief * groove * tint, 0.0, 0.88)

            h_map = np.zeros((y1 - y0, S), dtype=np.float32)
            s_map = np.zeros((y1 - y0, S), dtype=np.float32)
            h_map[ok] = h_mix
            s_map[ok] = s_mix
            h_map = _flat_fill(h_map, ok)
            dx, dy = _height_to_normal_tangent(h_map, strength=3.1 if prof["detail"] != "wing" else 4.2)

            # Normale de base : celle du GLB 1024 relue (forme large) + gradient fin 4K
            n_blk = np.full((y1 - y0, S, 3), 0.5, dtype=np.float32)
            n_blk[..., 2] = 1.0
            ts = n_blk * 2.0 - 1.0
            ts[..., 0] -= dx
            ts[..., 1] += dy
            ln = np.maximum(np.linalg.norm(ts, axis=2, keepdims=True), 1e-8)
            n_blk = np.clip(ts / ln * 0.5 + 0.5, 0.0, 1.0)

            o_blk = np.ones((y1 - y0, S, 3), dtype=np.float32)
            o_blk[..., 0] = np.clip((1.0 - 0.52 * seam_w * s_map) * (0.90 + 0.14 * h_map), 0.12, 1.0)
            o_blk[..., 1] = np.clip(0.60 + 0.24 * seam_w * s_map - 0.12 * np.clip(h_map, 0, 1), 0.08, 0.94)
            o_blk[..., 2] = 0.0
            if ivory.any():
                hw = np.zeros((y1 - y0, S), dtype=np.float32)
                hw[ok] = ivory.astype(np.float32)
                o_blk[..., 1] = np.where(hw > 0.5, 0.20, o_blk[..., 1])

            out_bc[y0:y1][ok] = np.round(bc_px * 255).astype(np.uint8)
            out_n[y0:y1][ok] = np.round(n_blk[ok] * 255).astype(np.uint8)
            out_orm[y0:y1][ok] = np.round(o_blk[ok] * 255).astype(np.uint8)

        # Padding des marges d'îlots UV. Deux zones :
        #   * gouttière (<= R px de l'îlot) : copie du texel couvert le plus proche,
        #     pour que le mipmapping ne tire pas de couleur étrangère dans les coutures ;
        #   * fond lointain : ton neutre sombre (et normale/ORM neutres). Sans ça, le
        #     remplissage « plus proche voisin » inondait tout l'atlas de grandes taches
        #     beiges opaques (visibles dans les planches QA et dans les mips basses).
        if not cov.all() and cov.any():
            R = max(8, int(S // 64))
            # Pas de `dist` (4096² float64 = 134 Mo) : la distance est recalculée
            # par bande à partir des indices, ce qui coûte quelques Mo seulement.
            nidx = ndimage.distance_transform_edt(~cov, return_indices=True,
                                                  return_distances=False)
            bc_mid = np.clip(np.asarray(out_bc[cov], dtype=np.float32).mean(0) * 0.55, 0, 255).astype(np.uint8)
            neutrals = (
                (out_bc, bc_mid),
                (out_n, np.array([128, 128, 255], dtype=np.uint8)),
                (out_orm, np.array([255, 160, 0], dtype=np.uint8)),
            )
            for buf, neutral in neutrals:
                src = buf.copy()
                for yy in range(0, S, band):
                    yy1 = min(yy + band, S)
                    m = ~cov[yy:yy1]
                    if not m.any():
                        continue
                    r = nidx[0][yy:yy1][m]
                    c = nidx[1][yy:yy1][m]
                    buf[yy:yy1][m] = src[r, c]
                    rr, cc = np.nonzero(m)
                    f = ((nidx[0][yy:yy1][m] - (yy + rr)) ** 2
                         + (nidx[1][yy:yy1][m] - cc) ** 2) > R * R
                    if f.any():
                        blk = buf[yy:yy1]
                        blk[m] = np.where(f[:, None], neutral[None, :], blk[m])
                del src
            del nidx

        bc_pil = Image.fromarray(out_bc)
        n_gl = Image.fromarray(out_n)
        orm_pil = Image.fromarray(out_orm)
        nd_arr = np.asarray(n_gl).copy()
        nd_arr[..., 1] = 255 - nd_arr[..., 1]
        n_dx = Image.fromarray(nd_arr)

        tag = "".join(c if c.isalnum() or c == "_" else "_" for c in g_name)
        bc_pil.save(render_dir / f"T_{tag}_BC.png")
        n_dx.save(render_dir / f"T_{tag}_N.png")
        n_gl.save(render_dir / f"T_{tag}_N_gl.png")
        orm_pil.save(render_dir / f"T_{tag}_ORM.png")
        Image.fromarray(out_orm[..., 0]).save(render_dir / f"T_{tag}_AO.png")
        Image.fromarray((255 - out_orm[..., 0]).astype(np.uint8)).save(render_dir / f"T_{tag}_Cavity.png")
        Image.fromarray(np.full((S, S), 96, dtype=np.uint8)).save(render_dir / f"T_{tag}_MatID.png")

        written.append({"geometry": g_name, "tag": tag, "size": S})
        glb_mats.append((bc_pil, n_gl, orm_pil))
        del out_bc, out_n, out_orm, cov
        __import__("gc").collect()

    manifest = {
        "texture_size": S,
        "atlases": written,
        "maps": ["BC", "N (DirectX -Y)", "N_gl (OpenGL +Y)", "ORM (AO/Rough/Metal)", "AO", "Cavity", "MatID"],
        "photo_projection": bool(photo_path),
    }
    (render_dir / "photo_4k_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    if write_glb and glb_mats:
        p2d._replace_glb_images_in_place(game_glb, glb_mats, fmt="WEBP", flip_green=False, max_dim=S)
        ue_glb = out_p / "unreal" / f"SM_{name}.glb"
        if ue_glb.is_file():
            p2d._replace_glb_images_in_place(ue_glb, glb_mats, fmt="PNG", flip_green=True, max_dim=2048)
        if glb_mats:
            bc0, n0, orm0 = glb_mats[0]
            bc0.save(out_p / "unreal" / f"T_{name}_BC.png")
            orm0.save(out_p / "unreal" / f"T_{name}_ORM.png")
            nd = np.asarray(n0).copy()
            nd[..., 1] = 255 - nd[..., 1]
            Image.fromarray(nd).save(out_p / "unreal" / f"T_{name}_N.png")

    return {"render_4k_dir": str(render_dir), "atlases": len(written), "texture_size": S}


# --------------------------------------------------------------------------- #
# 5. Planche de contrôle 1:1 des détails 4K
# --------------------------------------------------------------------------- #

def make_4k_crop_sheet(
    out_dir: str | Path,
    name: str,
    out_png: str | Path,
    crop_px: int = 512,
    cols: int = 3,
) -> dict:
    """Colle des crops 1:1 (512 px) des cartes 4K : la preuve visuelle du niveau de détail."""
    out_p = Path(out_dir)
    render_dir = out_p / "render_4k"
    files = sorted(render_dir.glob("T_*_BC.png"))
    if not files:
        raise FileNotFoundError("aucune carte 4K dans render_4k/")
    bc = Image.open(files[0]).convert("RGB")
    S = bc.size[0]
    crop_px = int(min(max(64, crop_px), S // 2))
    nrm_p = render_dir / files[0].name.replace("_BC.png", "_N.png")
    orm_p = render_dir / files[0].name.replace("_BC.png", "_ORM.png")
    nrm = Image.open(nrm_p).convert("RGB") if nrm_p.is_file() else bc
    orm = Image.open(orm_p).convert("RGB") if orm_p.is_file() else bc

    # Centres choisis par densité de détail (gradient le plus fort) sur une grille
    arr = np.asarray(bc.convert("L"), dtype=np.float32)
    step = max(S // 12, 1)
    cand = []
    for yy in range(crop_px // 2, S - crop_px // 2, step * 2):
        for xx in range(crop_px // 2, S - crop_px // 2, step * 2):
            patch = arr[yy - 64:yy + 64, xx - 64:xx + 64]
            if patch.size == 0:
                continue
            cand.append((float(np.abs(np.gradient(patch)[0]).mean() + np.abs(np.gradient(patch)[1]).mean()), xx, yy))
    cand.sort(reverse=True)
    picks: list[tuple[int, int]] = []
    for _, xx, yy in cand:
        if all(abs(xx - px) > crop_px * 0.7 or abs(yy - py) > crop_px * 0.7 for px, py in picks):
            picks.append((xx, yy))
        if len(picks) >= cols * 2:
            break

    tile = crop_px
    rows = max(1, math.ceil(len(picks) / cols))
    sheet = Image.new("RGB", (cols * tile + 20, rows * (tile + 26) + 40), (14, 17, 23))
    from PIL import ImageDraw
    dr = ImageDraw.Draw(sheet)
    dr.text((12, 12), f"CROPS 1:1 (512 px) DES CARTES {S}px — {name} — micro-écailles, MEMBRANES & KÉRATINE", fill=(240, 246, 255))
    for i, (xx, yy) in enumerate(picks):
        cx = (i % cols) * tile + 10
        cy = (i // cols) * (tile + 26) + 34
        box = (xx - tile // 2, yy - tile // 2, xx + tile // 2, yy + tile // 2)
        sheet.paste(bc.crop(box), (cx, cy))
        dr.text((cx + 4, cy + tile + 4), f"BC 1:1 @({xx},{yy})", fill=(160, 220, 255))
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png)
    return {"out_png": str(out_png), "crops": len(picks), "size": S}
