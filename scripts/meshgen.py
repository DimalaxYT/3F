#!/usr/bin/env python3
"""
meshgen — génération 3D type Meshy v2 (SDF continu + vues ASCII ou vectorielles 2D),
100% déterministe, zéro API, zéro GPU.

Deux formats de vues supportés de façon transparente dans `spec["views"]` :
  * Vues ASCII classiques : liste de chaînes `["  s  ", " sss ", ...]`
  * Vues vectorielles 2D continues (zéro marche d'escalier) :
    `{"w": 120, "h": 400, "shapes": [{"kind": "spline"|"poly"|"rect"|"ellipse"|"capsule", ...}]}`

Pipeline :
  1. Représentation interne : silhouettes multi-vues (ASCII ou vectorielles 2D) + palette PBR.
  2. Alignement physique strict : Z-up (`ligne 0` = sommet `+Z`, bas = `z=0`),
     avant = `-Y` (`dernière col` de `side`, `dernière ligne` de `top`).
  3. Volume continu : champs de distance signée (SDF) 2D -> intersection CSG 3D
     `min(sdf_front, sdf_side, sdf_top)` + votes de matériaux multi-vues.
  4. Géométrie : marching cubes sur SDF lissé -> Taubin -> décimation quadrique
     (budget triangles) -> centrage XY & pose exacte à `z=0`.
  5. UV : unwrap xatlas (`pbr.unwrap`).
  6. Textures PBR : bake multi-cartes glTF 2.0 (`albedo` + `metallicRoughness` +
     `normal`) via `pbr.bake_textures` (`rust`, `wrap`, `edge_wear`, `wood_grain`,
     `brushed_metal`, `hamon`, `patina`, `speckle`).
  7. Cohérence & rendus : IoU 3 vues cohérent avec le repère + rendu PBR direct
     par pixel UV + normal map via `renderer.py`.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import time

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.interpolate import PchipInterpolator
from skimage import measure
import trimesh

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import pbr       # noqa: E402
import renderer  # noqa: E402

# Ré-export des primitives bruit/PBR pour rétro-compatibilité éventuelle
value_noise = pbr.value_noise
fbm = pbr.fbm
unwrap = pbr.unwrap
bake_textures = pbr.bake_textures
attach_visual = pbr.attach_visual

EMPTY = {".", " ", ""}


class SpecError(ValueError):
    pass


# --------------------------------------------------------------------------
# 1. Parsing des vues : ASCII classique OU canevas vectoriel 2D continu
# --------------------------------------------------------------------------

def _resolve_mat_index(mat_id: str, palette_ids: list[str], ctx: str) -> int:
    if mat_id in EMPTY or mat_id == "void":
        return -1
    if mat_id == "#":
        return 0
    if mat_id in palette_ids:
        return palette_ids.index(mat_id)
    raise SpecError(
        f"{ctx} : matériau '{mat_id}' absent de la palette "
        f"{'/'.join(palette_ids)} ('.' ou espace = vide)")


def _normalize_spec(spec: dict) -> dict:
    """Normalise les alias de schéma pour accepter aussi bien les specs
    concises (`materials`, `dims`, `grid`, `size`, `op`, `center/half_width`)
    que le schéma canonique (`palette`, `size_m`, `res`, `w/h/kind`)."""
    spec = dict(spec)
    if "palette" not in spec and isinstance(spec.get("materials"), dict):
        pal = []
        for mid, mdef in spec["materials"].items():
            pal.append({
                "id": str(mid),
                "name": str(mdef.get("name", mid)),
                "color": mdef.get("color", mdef.get("base", "#b0b4ba")),
                "metallic": float(mdef.get("metallic", 0.0)),
                "roughness": float(mdef.get("roughness", 0.55)),
            })
        spec["palette"] = pal
    if "dims" in spec and "size_m" not in spec:
        spec["size_m"] = float(max(spec["dims"]))
    return spec


def _spline_ribbon_polygon(ctrl_pts: list, n_samples: int = 128) -> list[tuple[float, float]]:
    """Convertit `[[x, y, half_w], ...]` en polygone ruban lisse sans overshoot."""
    arr = np.asarray(ctrl_pts, dtype=float)
    if arr.ndim != 2 or arr.shape[1] < 3 or len(arr) < 2:
        raise SpecError("shape 'spline' attend pts=[[x, y, half_w], ...] (N>=2)")
    seg = np.hypot(np.diff(arr[:, 0]), np.diff(arr[:, 1]))
    t = np.concatenate([[0.0], np.cumsum(np.maximum(seg, 1e-6))])
    t /= t[-1]
    ts = np.linspace(0.0, 1.0, n_samples)
    xs = PchipInterpolator(t, arr[:, 0])(ts)
    ys = PchipInterpolator(t, arr[:, 1])(ts)
    ws = np.maximum(PchipInterpolator(t, arr[:, 2])(ts), 0.0)
    dx = np.gradient(xs)
    dy = np.gradient(ys)
    ln = np.hypot(dx, dy)
    ln = np.where(ln < 1e-9, 1.0, ln)
    nx, ny = -dy / ln, dx / ln
    # Adoucit les extrémités fines pour éviter toute moustache d'interpolation PCHIP
    ws = ndimage.gaussian_filter1d(ws, sigma=1.2, mode="nearest")
    left = list(zip((xs + nx * ws).tolist(), (ys + ny * ws).tolist()))
    right = list(zip((xs - nx * ws)[::-1].tolist(), (ys - ny * ws)[::-1].tolist()))
    return left + right


def _capsule_polygon(p0, p1, r: float, n_arc: int = 16) -> list[tuple[float, float]]:
    x0, y0 = float(p0[0]), float(p0[1])
    x1, y1 = float(p1[0]), float(p1[1])
    ang = math.atan2(y1 - y0, x1 - x0)
    pts = []
    for a in np.linspace(ang + math.pi * 0.5, ang + math.pi * 1.5, n_arc):
        pts.append((x0 + r * math.cos(a), y0 + r * math.sin(a)))
    for a in np.linspace(ang - math.pi * 0.5, ang + math.pi * 0.5, n_arc):
        pts.append((x1 + r * math.cos(a), y1 + r * math.sin(a)))
    return pts


def parse_vector_view(vspec: dict, palette_ids: list[str], view_name: str,
                      super_res: int = 384):
    """Rastérise un canevas vectoriel 2D `{"w": W, "h": H, "shapes": [...]}`
    (ou `{"size": [W, H], "shapes": [...]}`) en haute résolution sans escalier."""
    if "size" in vspec and isinstance(vspec["size"], (list, tuple)) and len(vspec["size"]) >= 2:
        w_log, h_log = float(vspec["size"][0]), float(vspec["size"][1])
    else:
        w_log = float(vspec.get("w", 100.0))
        h_log = float(vspec.get("h", 100.0))
    if w_log <= 0 or h_log <= 0:
        raise SpecError(f"vue vectorielle '{view_name}' : w et h doivent être > 0")
    shapes = vspec.get("shapes")
    if not isinstance(shapes, list) or not shapes:
        raise SpecError(f"vue vectorielle '{view_name}' : liste 'shapes' requise")

    scale = super_res / max(w_log, h_log)
    W_px = max(8, int(round(w_log * scale)))
    H_px = max(8, int(round(h_log * scale)))
    sx = (W_px - 1) / w_log
    sy = (H_px - 1) / h_log

    # Image d'indices de palette décalés de +1 (0 = vide, k+1 = palette[k])
    canvas = Image.new("I", (W_px, H_px), 0)
    dr = ImageDraw.Draw(canvas)

    for si, sh in enumerate(shapes):
        kind = sh.get("kind", sh.get("op", "poly"))
        mat_idx = _resolve_mat_index(str(sh.get("mat", "#")), palette_ids,
                                     f"vue '{view_name}' shape[{si}]")
        fill_val = 0 if sh.get("erase", False) or mat_idx < 0 else (mat_idx + 1)

        if kind == "rect":
            if "x0" in sh:
                x = float(sh["x0"]) * sx
                y = float(sh["y0"]) * sy
                w = (float(sh["x1"]) - float(sh["x0"])) * sx
                h = (float(sh["y1"]) - float(sh["y0"])) * sy
            else:
                x, y = float(sh["x"]) * sx, float(sh["y"]) * sy
                w, h = float(sh["w"]) * sx, float(sh["h"]) * sy
            rad = float(sh.get("r", 0.0)) * min(sx, sy)
            if rad > 0.5:
                dr.rounded_rectangle([x, y, x + w, y + h], radius=rad, fill=fill_val)
            else:
                dr.rectangle([x, y, x + w, y + h], fill=fill_val)
        elif kind in ("ellipse", "circle"):
            cx, cy = float(sh["cx"]) * sx, float(sh["cy"]) * sy
            rx = float(sh.get("rx", sh.get("r", 1.0))) * sx
            ry = float(sh.get("ry", sh.get("r", 1.0))) * sy
            dr.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=fill_val)
        elif kind == "poly":
            pts = [(float(p[0]) * sx, float(p[1]) * sy) for p in sh["pts"]]
            if len(pts) >= 3:
                dr.polygon(pts, fill=fill_val)
        elif kind == "capsule":
            p0 = sh.get("p0", sh.get("a"))
            p1 = sh.get("p1", sh.get("b"))
            pts = _capsule_polygon(p0, p1, float(sh["r"]))
            dr.polygon([(p[0] * sx, p[1] * sy) for p in pts], fill=fill_val)
        elif kind == "spline":
            if "pts" in sh:
                ctrl = sh["pts"]
            else:
                # Syntaxe profil vertical : center=[[y, x], ...], half_width=[[y, hw], ...]
                c_arr = np.asarray(sh["center"], dtype=float)
                hw_arr = np.asarray(sh["half_width"], dtype=float)
                ys = np.unique(np.concatenate([c_arr[:, 0], hw_arr[:, 0]]))
                ys.sort()
                xs_i = PchipInterpolator(c_arr[:, 0], c_arr[:, 1])(ys)
                hw_i = PchipInterpolator(hw_arr[:, 0], hw_arr[:, 1])(ys)
                ctrl = np.column_stack([xs_i, ys, hw_i]).tolist()
            pts = _spline_ribbon_polygon(ctrl, n_samples=int(sh.get("samples", 128)))
            dr.polygon([(p[0] * sx, p[1] * sy) for p in pts], fill=fill_val)
        else:
            raise SpecError(f"vue '{view_name}' : kind='{kind}' inconnu")

    arr = np.asarray(canvas, dtype=np.int32) - 1
    return arr >= 0, arr


def parse_view(rows, palette_ids, view_name):
    """Vue ASCII ou vectorielle 2D -> `(mask H×W bool, zones H×W int)`.
    `zones` : `-1` = vide, sinon index palette (`'#'` = `0` = matériau principal)."""
    if isinstance(rows, dict):
        return parse_vector_view(rows, palette_ids, view_name)
    if not rows or not isinstance(rows, list):
        raise SpecError(f"vue '{view_name}' : liste de lignes ou dict vectoriel attendu")
    W = max(len(r) for r in rows)
    if W < 2:
        raise SpecError(f"vue '{view_name}' : trop étroite")
    grid = np.full((len(rows), W), -1, dtype=np.int32)
    for r, line in enumerate(rows):
        for c, ch in enumerate(line):
            if ch in EMPTY:
                continue
            grid[r, c] = _resolve_mat_index(
                ch, palette_ids, f"vue '{view_name}' ligne {r} col {c}")
    return grid != -1, grid


def _resize_nearest(arr, shape):
    im = Image.fromarray(np.ascontiguousarray(arr))
    im = im.resize((shape[1], shape[0]), Image.NEAREST)
    return np.asarray(im)


def _signed_distance_2d(mask: np.ndarray, out_shape: tuple[int, int]) -> np.ndarray:
    """SDF 2D lisse (positif à l'intérieur, négatif à l'extérieur) ré-échantillonné
    vers `out_shape = (H_out, W_out)` en interpolation bilinéaire continue."""
    # Sur-échantillonne les petites grilles ASCII de façon anti-crénelée pour
    # lisser les diagonales tout en préservant l'épaisseur des traits 1-2 px.
    m = mask.astype(np.float32)
    h, w = m.shape
    if max(h, w) < 128:
        up = max(2, int(math.ceil(128.0 / max(h, w))))
        m_hi = ndimage.zoom(m, up, order=1, mode="nearest")
        m_bool = m_hi >= 0.5
    else:
        m_bool = mask
    d_in = ndimage.distance_transform_edt(m_bool)
    d_out = ndimage.distance_transform_edt(~m_bool)
    sdf = (d_in - d_out).astype(np.float32)
    zh = out_shape[0] / sdf.shape[0]
    zw = out_shape[1] / sdf.shape[1]
    scale_norm = 0.5 * (zh + zw)
    return ndimage.zoom(sdf, (zh, zw), order=1, mode="nearest") * scale_norm


# --------------------------------------------------------------------------
# 2-3. Visual hull SDF continu + votes de matériaux alignés Z-up / -Y avant
# --------------------------------------------------------------------------

def build_volumes(spec):
    """Extrude les 3 vues et intersecte -> `(occ, zone, dims_grille, masks_in)`.
    Axes Z-up stricts :
      * `front` : col 0..W-1 -> `-X..+X`, ligne 0 = `+Z` (sommet), fin = `z=0` (sol)
      * `side`  : col 0 = `+Y` (arrière), fin = `-Y` (avant) ; ligne 0 = `+Z`
      * `top`   : col 0..W-1 -> `-X..+X` ; ligne 0 = `+Y` (arrière), fin = `-Y` (avant)
    """
    spec = _normalize_spec(spec)
    pal = [m["id"] for m in spec["palette"]]
    mf, zf = parse_view(spec["views"]["front"], pal, "front")
    ms, zs = parse_view(spec["views"]["side"], pal, "side")
    mt, zt = parse_view(spec["views"]["top"], pal, "top")

    if "grid" in spec and isinstance(spec["grid"], (list, tuple)) and len(spec["grid"]) == 3:
        gx, gy, gz = [max(6, int(v)) for v in spec["grid"]]
    else:
        R = int(spec.get("res", 80))
        x_u = float(mf.shape[1])
        y_u = float(ms.shape[1]) * (float(mf.shape[0]) / max(1.0, float(ms.shape[0])))
        z_u = float(mf.shape[0])
        m_u = max(x_u, y_u, z_u)
        gx = max(6, round(R * x_u / m_u))
        gy = max(6, round(R * y_u / m_u))
        gz = max(6, round(R * z_u / m_u))

    # Orientation monde : index 0 = (-X, -Y=avant, z=0=sol) — contigu requis par Pillow !
    mf_w, zf_w = np.ascontiguousarray(mf[::-1, :]), np.ascontiguousarray(zf[::-1, :])
    ms_w, zs_w = np.ascontiguousarray(ms[::-1, ::-1]), np.ascontiguousarray(zs[::-1, ::-1])
    mt_w, zt_w = np.ascontiguousarray(mt[::-1, :]), np.ascontiguousarray(zt[::-1, :])

    # 1) Grille logique (gx, gy, gz) + SDF 2D continu pour une géométrie lisse
    sdf_f = _signed_distance_2d(mf_w, (gz, gx)).T[:, None, :]   # (gx, 1, gz)
    sdf_s = _signed_distance_2d(ms_w, (gz, gy)).T[None, :, :]   # (1, gy, gz)
    sdf_t = _signed_distance_2d(mt_w, (gy, gx)).T[:, :, None]   # (gx, gy, 1)
    sdf_3d = np.minimum(np.minimum(sdf_f, sdf_s), sdf_t)

    mf_g = _resize_nearest(mf_w.astype(np.uint8), (gz, gx)).astype(bool)
    ms_g = _resize_nearest(ms_w.astype(np.uint8), (gz, gy)).astype(bool)
    mt_g = _resize_nearest(mt_w.astype(np.uint8), (gy, gx)).astype(bool)
    occ_bin = (np.broadcast_to(mf_g.T[:, None, :], (gx, gy, gz))
               & np.broadcast_to(ms_g.T[None, :, :], (gx, gy, gz))
               & np.broadcast_to(mt_g.T[:, :, None], (gx, gy, gz)))
    occ = (sdf_3d >= 0.0) | occ_bin
    if not occ.any():
        raise SpecError("visual hull vide : les 3 vues ne se recouvrent pas")

    occ = _fill_closed_cavities(occ, spec)

    zf_g = _resize_nearest(zf_w.astype(np.int32), (gz, gx))
    zs_g = _resize_nearest(zs_w.astype(np.int32), (gz, gy))
    zt_g = _resize_nearest(zt_w.astype(np.int32), (gy, gx))
    Z_f = np.broadcast_to(zf_g.T[:, None, :], (gx, gy, gz))
    Z_s = np.broadcast_to(zs_g.T[None, :, :], (gx, gy, gz))
    Z_t = np.broadcast_to(zt_g.T[:, :, None], (gx, gy, gz))

    if spec.get("symmetry_x", True):
        diff = int((occ ^ occ[::-1, :, :]).sum())
        if diff * 20 > int(occ.sum()):
            print(f"  ⚠ symmetry_x=true mais les vues sont asymétriques "
                  f"({diff} voxels hors miroir) : les détails décentrés "
                  f"seront dupliqués en miroir — symmetry_x: false si non voulu")
        occ = occ | occ[::-1, :, :]
        sdf_3d = np.maximum(sdf_3d, sdf_3d[::-1, :, :])

    votes = np.stack([Z_f, Z_s, Z_t])
    valid = votes >= 0
    P = len(pal)
    counts = np.zeros((P,) + occ.shape, dtype=np.int16)
    for p in range(P):
        counts[p] = ((votes == p) & valid).sum(0)
    zone = counts.argmax(0).astype(np.int8)
    zone[~occ] = -1

    if spec.get("symmetry_x", True):
        zm = zone[::-1, :, :]
        zone = np.where(zone >= 0, zone, zm)

    spec["_sdf_cache"] = sdf_3d
    return occ, zone, (gx, gy, gz), (mf, ms, mt)


# --------------------------------------------------------------------------
# 4. Géométrie : marching cubes SDF + lissage + décimation + pose z=0
# --------------------------------------------------------------------------

def _sample_labels(zone_up, coords):
    """Labels aux sommets, avec réparation par transformée en distance 3D."""
    idx = np.clip(coords, 0, np.array(zone_up.shape) - 1)
    lab = zone_up[idx[:, 0], idx[:, 1], idx[:, 2]]
    if (lab < 0).any():
        occ_up = zone_up >= 0
        ind = ndimage.distance_transform_edt(
            ~occ_up, return_distances=False, return_indices=True)
        near = zone_up[ind[0, idx[:, 0], idx[:, 1], idx[:, 2]],
                       ind[1, idx[:, 0], idx[:, 1], idx[:, 2]],
                       ind[2, idx[:, 0], idx[:, 1], idx[:, 2]]]
        lab = np.where(lab < 0, near, lab)
    return np.clip(lab, 0, None)


def _remove_debris(mesh, spec):
    """Supprime les îlots résiduels (< `debris_min_faces` faces)."""
    min_faces = int(spec.get("debris_min_faces", 50))
    parts = mesh.split(only_watertight=False)
    if len(parts) < 2:
        return
    big = [p for p in parts if len(p.faces) >= min_faces]
    gone = len(parts) - len(big)
    if not big or not gone:
        return
    cleaned = trimesh.util.concatenate(big)
    mesh.vertices = cleaned.vertices
    mesh.faces = cleaned.faces
    mesh.metadata["debris_removed"] = gone


def _fill_closed_cavities(occ, spec):
    """Comble les cavités internes fermées en préservant les creux ouverts."""
    if not spec.get("fill_cavities", True):
        return occ
    filled = ndimage.binary_fill_holes(occ)
    gain = int(filled.sum() - occ.sum())
    if gain > 0:
        print(f"  cavités fermées comblées : +{gain} voxels "
              f"(coque dessinée en anneau ?)")
        return filled
    return occ


def mesh_from_volumes(occ, zone, spec):
    sdf_cached = spec.pop("_sdf_cache", None)
    P = 3
    occ_p = np.pad(occ, P, constant_values=False)
    zone_p = np.pad(zone, P, constant_values=-1)

    up = int(spec.get("upsample", 1 if max(occ.shape) >= 120 else 2))
    zone_up = np.repeat(np.repeat(np.repeat(zone_p, up, 0), up, 1), up, 2)

    if sdf_cached is not None and sdf_cached.shape == occ.shape:
        # Utilise le champ SDF continu + cavités comblées pour éviter les escaliers
        sdf_clean = np.where(occ & (sdf_cached < 0.0), 0.35, sdf_cached)
        sdf_pad = np.pad(sdf_clean, P, constant_values=-3.0)
        vol = ndimage.zoom(sdf_pad.astype(np.float32), up, order=1, mode="nearest")
        vol = ndimage.gaussian_filter(vol, sigma=float(spec.get("sdf_sigma", 0.55)))
        # Convertit mc_level (convention historique [0..1] centrée sur 0.5) en offset SDF
        iso = (float(spec.get("mc_level", 0.5)) - 0.5) * 1.5
        verts, faces, _, _ = measure.marching_cubes(vol, level=iso)
    else:
        vol = ndimage.zoom(occ_p.astype(np.float32), up, order=1, mode="nearest")
        verts, faces, _, _ = measure.marching_cubes(
            vol, level=float(spec.get("mc_level", 0.5)))

    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    trimesh.repair.fix_normals(mesh)
    trimesh.repair.fill_holes(mesh)

    n_smooth = int(spec.get("smooth", 8))
    if n_smooth > 0:
        trimesh.smoothing.filter_taubin(mesh, lamb=0.5, nu=-0.53,
                                        iterations=n_smooth)
    mesh.process(validate=True)
    _remove_debris(mesh, spec)

    # Échantillonnage des matériaux AVANT mise à l'échelle et centrage monde
    vox_coords = mesh.vertices.copy()
    v_labels = _sample_labels(zone_up, np.rint(vox_coords).astype(np.int64))

    ext = mesh.bounds[1] - mesh.bounds[0]
    if "dims" in spec and isinstance(spec["dims"], (list, tuple)) and len(spec["dims"]) == 3:
        target = np.asarray(spec["dims"], dtype=float)
        scale_vec = target / np.maximum(1e-9, ext)
        mesh.vertices = mesh.vertices * scale_vec
    else:
        size_m = float(spec.get("size_m", 1.0))
        scale_vec = np.full(3, size_m / max(1e-9, float(ext.max())), dtype=float)
        mesh.vertices = mesh.vertices * scale_vec

    budget = int(spec.get("budget_tris", 15000))
    if len(mesh.faces) > budget:
        keep = mesh.copy()
        keep_labels = v_labels
        for b in (budget, budget * 2, budget * 4):
            cand = mesh.simplify_quadric_decimation(face_count=b)
            trimesh.repair.fill_holes(cand)
            trimesh.repair.fix_normals(cand)
            if cand.is_watertight:
                mesh = cand
                v_labels = _sample_labels(
                    zone_up,
                    np.rint(mesh.vertices / scale_vec).astype(np.int64))
                break
        if not mesh.is_watertight:
            mesh, v_labels = keep, keep_labels

    # Convention 3d-forge : centré en XY, base exactement posée sur le sol z = 0
    lo, hi = mesh.bounds
    cx = 0.5 * (lo[0] + hi[0])
    cy = 0.5 * (lo[1] + hi[1])
    mesh.apply_translation([-cx, -cy, -lo[2]])
    return mesh, v_labels


# --------------------------------------------------------------------------
# 7. Cohérence : IoU des silhouettes re-projetées vs vues d'entrée
# --------------------------------------------------------------------------

def silhouette_iou(mesh, views_masks, grid_shape, size_m):
    """Re-projette le mesh final sur les 3 plans (exactement alignés avec
    `build_volumes`) et mesure l'IoU de silhouette."""
    gx, gy, gz = grid_shape
    lo, hi = mesh.bounds
    ious = {}
    plan = {
        # (axe_u, axe_v, W, H, mask, flip_u, flip_v)
        "front": (0, 2, max(gx * 4, 64), max(gz * 4, 64), views_masks[0], False, True),
        "side":  (1, 2, max(gy * 4, 64), max(gz * 4, 64), views_masks[1], True,  True),
        "top":   (0, 1, max(gx * 4, 64), max(gy * 4, 64), views_masks[2], False, True),
    }
    v = mesh.vertices
    faces = mesh.faces
    for name, (ax_u, ax_v, Wg, Hg, mask_in, flip_u, flip_v) in plan.items():
        H_in, W_in = mask_in.shape
        img = Image.new("L", (Wg, Hg), 0)
        d = ImageDraw.Draw(img)
        su = (Wg - 1) / max(1e-9, hi[ax_u] - lo[ax_u])
        sv = (Hg - 1) / max(1e-9, hi[ax_v] - lo[ax_v])
        pu = (v[:, ax_u] - lo[ax_u]) * su
        pv = (v[:, ax_v] - lo[ax_v]) * sv
        if flip_u:
            pu = (Wg - 1) - pu
        if flip_v:
            pv = (Hg - 1) - pv
        tri = np.stack([pu[faces], pv[faces]], axis=-1)
        for pts in tri.tolist():
            d.polygon([(pts[0][0], pts[0][1]),
                       (pts[1][0], pts[1][1]),
                       (pts[2][0], pts[2][1])], fill=255)
        sil = np.asarray(img.resize((W_in, H_in), Image.BILINEAR)) > 96
        inter = int((sil & mask_in).sum())
        union = int((sil | mask_in).sum())
        ious[name] = round(inter / union, 4) if union else 0.0
    return ious


def save_view_maps(views, palette, outdir, stem):
    """Sauvegarde les 3 vues internes (ASCII ou vectorielles 2D) en PNG colorés."""
    pal_ids = [m["id"] for m in palette]
    pal_rgb = [tuple((pbr._hex2rgb(m["color"]) * 255).astype(int).tolist())
               for m in palette]
    paths = []
    for name, raw in views.items():
        _, zones = parse_view(raw, pal_ids, name)
        H, W = zones.shape
        arr = np.full((H, W, 3), (18, 18, 22), dtype=np.uint8)
        for k, rgb in enumerate(pal_rgb):
            arr[zones == k] = rgb
        im = Image.fromarray(arr)
        scale = max(1, 256 // max(H, W))
        if scale > 1:
            im = im.resize((W * scale, H * scale), Image.NEAREST)
        p = os.path.join(outdir, f"{stem}_view_{name}.png")
        im.save(p)
        paths.append(p)
    return paths


# --------------------------------------------------------------------------
# Pipeline complet
# --------------------------------------------------------------------------

def load_references(ref_path, outdir, stem):
    if os.path.isdir(ref_path):
        ref_path = os.path.join(ref_path, "references.json")
    if not os.path.isfile(ref_path):
        print(f"[references] introuvable : {ref_path} (étape recherche web "
              "sautée ?) — voir research.py", file=sys.stderr)
        return None
    with open(ref_path) as fh:
        refs = json.load(fh)
    out = {"n_images": refs.get("n_images", 0),
           "queries": refs.get("queries", []),
           "details_to_respect": refs.get("details_to_respect", []),
           "palette_hints": refs.get("palette_hints", [])}
    sheet = refs.get("sheet")
    if sheet and os.path.isfile(sheet):
        dst = os.path.join(outdir, f"{stem}_references.png")
        shutil.copyfile(sheet, dst)
        out["sheet"] = os.path.abspath(dst)
    return out


def generate(spec, outdir, res_override=None, budget_override=None,
             faces_all=False, references_path=None, name_override=None):
    t0 = time.time()
    spec = _normalize_spec(spec)
    if name_override:
        spec["name"] = name_override
    os.makedirs(outdir, exist_ok=True)
    stem = spec.get("name", "objet")
    if res_override:
        spec["res"] = res_override
    if budget_override:
        spec["budget_tris"] = budget_override

    # 1-3 : vues -> volumes SDF
    occ, zone, grid_shape, masks = build_volumes(spec)
    # 4 : géométrie posée à z=0
    mesh, v_labels = mesh_from_volumes(occ, zone, spec)
    # 5 : UV
    mesh, labels, uv = unwrap(mesh, v_labels)
    # 6 : textures PBR (albedo + metallicRoughness + normal)
    albedo_img, mr_img, normal_img, _ = bake_textures(mesh, labels, uv, spec)
    attach_visual(mesh, uv, albedo_img, mr_img, normal_img)
    trimesh.repair.fix_winding(mesh)

    solid = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces, process=True)
    solid.merge_vertices()
    checks = {
        "watertight": bool(solid.is_watertight),
        "winding_consistent": bool(solid.is_winding_consistent),
        "volume_m3": float(abs(solid.volume)) if solid.is_watertight else 0.0,
        "triangles": int(len(mesh.faces)),
        "vertices": int(len(mesh.vertices)),
        "components": int(solid.body_count),
        "debris_removed": int(mesh.metadata.get("debris_removed", 0)),
        "degenerate_faces": int((~solid.nondegenerate_faces()).sum()),
        "over_budget": len(mesh.faces) > int(spec.get("budget_tris", 15000)),
    }
    # 7 : cohérence multi-vues
    ious = silhouette_iou(mesh, masks, grid_shape, float(spec.get("size_m", 1.0)))
    checks["iou_views"] = ious
    checks["iou_mean"] = round(sum(ious.values()) / len(ious), 4)

    # Exports
    scene = trimesh.Scene(mesh)
    files = {}
    glb = os.path.join(outdir, stem + ".glb")
    scene.export(glb)
    files["glb"] = glb
    obj = os.path.join(outdir, stem + ".obj")
    try:
        import meshkit as mk
        mk.export_obj_with_mtl(scene, obj)
        files["obj"] = obj
    except Exception as e:
        print(f"  ⚠ export OBJ a échoué ({type(e).__name__}: {e}) "
              f"— le GLB/STL restent valides", file=sys.stderr)
    stl = os.path.join(outdir, stem + ".stl")
    solid.export(stl)
    files["stl"] = stl
    try:
        import usdz_export
        usd = os.path.join(outdir, stem + ".usdz")
        usdz_export.export_usdz(scene, usd)
        files["usdz"] = usd
    except Exception as e:
        print(f"  ⚠ export USDZ a échoué ({type(e).__name__}: {e}) "
              f"— le GLB reste valide", file=sys.stderr)
    albedo_img.save(os.path.join(outdir, stem + "_albedo.png"))
    files["albedo"] = os.path.join(outdir, stem + "_albedo.png")

    # Rendus de contrôle PBR directs (sampling UV + metallicRoughness + normal map par pixel !)
    views_def = [("face", 0, 8), ("profil", 90, 8), ("trois_quarts", 42, 22),
                 ("dessus", 0, 78)]
    renders = []
    for label, az, el in views_def:
        img = renderer.render_view(scene, azimuth_deg=az, elevation_deg=el,
                                   size=768, ssaa=2)
        p = os.path.join(outdir, f"{stem}_{label}.png")
        img.save(p)
        renders.append(p)

    view_maps = save_view_maps(spec["views"], spec["palette"], outdir, stem)

    photos = {}
    if faces_all:
        face_paths, faces_sheet = renderer.render_all_faces(scene, outdir, stem,
                                                            size=768)
        turn_paths, turn_sheet = renderer.render_turntable(
            scene, outdir, stem, n=int(spec.get("turntable", 8)), size=560)
        photos = {"faces": face_paths, "all_faces": faces_sheet,
                  "turn_images": turn_paths, "turntable": turn_sheet}

    refs_summary = None
    ref_src = references_path or spec.get("references")
    if ref_src:
        refs_summary = load_references(ref_src, outdir, stem)

    is_vec = any(isinstance(v, dict) for v in spec["views"].values())
    report = {
        "pipeline": ("meshgen v2 (visual hull SDF vectoriel multi-vues, PBR complet)"
                     if is_vec else
                     "meshgen v2 (visual hull SDF multi-vues, PBR complet)"),
        "prompt": spec.get("prompt", ""),
        "params": {k: spec[k] for k in ("res", "budget_tris", "size_m", "smooth")
                   if k in spec},
        "stats": {"parts": 1, "triangles": checks["triangles"],
                  "vertices": checks["vertices"]},
        "validation": checks,
        "coherence": {"method": "IoU silhouettes re-projetées vs vues d'entrée",
                      "per_view": ious, "mean": checks["iou_mean"]},
        "files": {k: {"path": v, "bytes": os.path.getsize(v)}
                  for k, v in files.items() if os.path.exists(v)},
        "renders": renders,
        "internal_views": view_maps,
        "output_dir": os.path.abspath(outdir),
        "duration_s": round(time.time() - t0, 2),
    }
    if photos:
        report["photos"] = {
            "all_faces": photos["all_faces"],
            "faces": photos["faces"],
            "turntable": photos["turntable"],
            "turn_images": photos["turn_images"],
        }
    if refs_summary:
        report["references"] = refs_summary
    with open(os.path.join(outdir, "report.json"), "w") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    return report


def main():
    ap = argparse.ArgumentParser(description="Génération 3D multi-vues SDF + PBR (zéro API)")
    ap.add_argument("spec", help="JSON de spec (vues ASCII ou vectorielles 2D + palette + overlays)")
    ap.add_argument("--out", required=True, help="répertoire de sortie")
    ap.add_argument("--name", default=None, help="préfixe des fichiers générés")
    ap.add_argument("--res", type=int, default=None, help="résolution grille")
    ap.add_argument("--budget", type=int, default=None, help="budget triangles")
    ap.add_argument("--faces", choices=["all"], default=None,
                    help="all = photos des 6 faces + turntable (livraison Meshy)")
    ap.add_argument("--usdz", action="store_true",
                    help="accepté pour compatibilité CLI (USDZ exporté d'office)")
    ap.add_argument("--references", default=None,
                    help="references.json (research.py) : planche des détails "
                         "à respecter, copiée + checklist dans le rapport")
    ap.add_argument("--no-preview", action="store_true",
                    help="ne pas générer la preview.html interactive")
    args = ap.parse_args()
    with open(args.spec) as fh:
        spec = json.load(fh)
    report = generate(spec, args.out, args.res, args.budget,
                      faces_all=(args.faces == "all"),
                      references_path=args.references,
                      name_override=args.name)
    v = report["validation"]
    print(f"OK {report['params'].get('res', '?')} -> {v['triangles']} tris, "
          f"watertight={v['watertight']}, IoU={report['coherence']['mean']} "
          f"({report['duration_s']}s)")
    for view, i in v["iou_views"].items():
        print(f"   IoU {view}: {i}")
    if not args.no_preview:
        try:
            import preview
            p = preview.build_preview(
                args.out, title=spec.get("prompt") or spec.get("name"),
                glb=report["files"]["glb"]["path"], report=report)
            if p:
                print(f"   preview → {p}")
        except Exception as e:
            print(f"[preview] échec ({e}) — génération conservée", file=sys.stderr)


if __name__ == "__main__":
    main()
