"""
renderer — rendu PNG multi-angles par rasterisation logicielle différée (numpy), sans GPU.

Caractéristiques :
  * rasterisation différée par buckets vectorisés + z-buffer exact (rapide, zéro overdraw)
  * anti-aliasing par sur-échantillonnage (SSAA 2x + Lanczos)
  * sampling PBR par pixel : baseColorTexture + metallicRoughnessTexture (bilinéaire
    perspectivement correct) + normalTexture (repère tangent dérivé par face)
  * ombrage Blinn-Phong à 3 lumières (key / fill / rim) + approx Fresnel & studio ACES
  * transparence multi-couches triée dos-vers-avant (layer peeling exact pour le verre)
  * ombre de contact douce accélérée C (ImageDraw) projetée au sol
"""
from __future__ import annotations

import math
import os
import numpy as np
from scipy import ndimage
import trimesh
from PIL import Image, ImageFilter, ImageDraw, ImageFont

DEFAULT_VIEWS = {
    "front":         (0.0, 14.0),
    "three_quarter": (42.0, 22.0),
    "side":          (90.0, 14.0),
    "top":           (0.0, 70.0),
    "back":          (180.0, 14.0),
    "left":          (270.0, 14.0),
    "bottom":        (0.0, -70.0),
    "back_three_quarter": (137.0, 22.0),
}

# les 6 faces canoniques d'un objet (photos obligatoires avant livraison)
ALL_FACES = [
    ("face",    0.0,   8.0),
    ("dos",     180.0, 8.0),
    ("gauche",  270.0, 8.0),
    ("droite",  90.0,  8.0),
    ("dessus",  0.0,   78.0),
    ("dessous", 0.0,  -78.0),
]

BG_TOP = np.array([0.93, 0.94, 0.96])
BG_BOTTOM = np.array([0.99, 0.99, 0.995])
AMBIENT = 0.33
EXPOSURE = 1.12
ENV_SKY = np.array([1.00, 1.02, 1.06])   # environnement hémisphérique (approx studio)
ENV_GND = np.array([0.30, 0.28, 0.27])


# --------------------------------------------------------------------------- #
# Extraction scène & matériaux / textures PBR
# --------------------------------------------------------------------------- #

def _img_float(im, channels=3):
    if im is None:
        return None
    mode = "RGBA" if channels == 4 else "RGB"
    arr = np.asarray(im.convert(mode), dtype=np.float32) / 255.0
    return arr[..., :channels]


def _sample_tex_bilinear(tex: np.ndarray, uv: np.ndarray) -> np.ndarray:
    """Échantillonnage bilinéaire vectorisé d'une texture `(H, W, C)` aux `uv` `(M, 2)`
    (convention OpenGL / trimesh : `u` gauche->droite, `v` bas->haut)."""
    th, tw = tex.shape[:2]
    fx = np.clip(uv[:, 0], 0.0, 1.0) * (tw - 1)
    fy = np.clip(1.0 - uv[:, 1], 0.0, 1.0) * (th - 1)
    x0 = np.floor(fx).astype(np.int64)
    y0 = np.floor(fy).astype(np.int64)
    x1 = np.minimum(x0 + 1, tw - 1)
    y1 = np.minimum(y0 + 1, th - 1)
    tx = (fx - x0)[:, None]
    ty = (fy - y0)[:, None]
    c00 = tex[y0, x0]
    c10 = tex[y0, x1]
    c01 = tex[y1, x0]
    c11 = tex[y1, x1]
    return ((c00 * (1.0 - tx) + c10 * tx) * (1.0 - ty)
            + (c01 * (1.0 - tx) + c11 * tx) * ty)


def _material_params(mesh: trimesh.Trimesh) -> dict:
    vis = getattr(mesh, "visual", None)
    m = getattr(vis, "material", None)
    col = getattr(m, "baseColorFactor", None)
    col = np.asarray(col, dtype=float) if col is not None else np.array([0.75, 0.75, 0.75, 1.0])
    if col.max() > 1.001:
        col = col / 255.0
    emis = getattr(m, "emissiveFactor", None)
    emis = np.asarray(emis, dtype=float) if emis is not None else np.zeros(3)
    if emis.max() > 2.001 and emis.max() <= 255.0:
        emis = emis / 255.0
    # Intensité HDR (KHR_materials_emissive_strength, ou attribut interne)
    strength = float(getattr(m, "_forge_emissive_strength", 0.0) or 0.0)
    if strength <= 0.0:
        ext_d = getattr(m, "extensions", None) or {}
        strength = float((ext_d.get("KHR_materials_emissive_strength") or {})
                         .get("emissiveStrength", 1.0) or 1.0)
    emis = emis * max(strength, 1.0)
    opacity = float(col[3]) if len(col) > 3 else 1.0

    uv = getattr(vis, "uv", None)
    has_uv = uv is not None and len(uv) == len(mesh.vertices)
    uv_arr = np.asarray(uv, dtype=np.float64) if has_uv else None

    albedo_tex = None
    mr_tex = None
    normal_tex = None
    if has_uv:
        raw_alb = getattr(m, "baseColorTexture", None) or getattr(vis, "image", None)
        albedo_tex = _img_float(raw_alb, 3)
        mr_img = _img_float(getattr(m, "metallicRoughnessTexture", None), 3)
        if mr_img is not None:
            mr_tex = mr_img
        nm_img = _img_float(getattr(m, "normalTexture", None), 3)
        if nm_img is not None:
            normal_tex = nm_img * 2.0 - 1.0
            normal_scale = float(getattr(m, "normalTextureScale", 1.0) or 1.0)
            normal_tex[..., :2] *= normal_scale

    return {
        "color": col[:3].copy(),
        "metallic": float(getattr(m, "metallicFactor", None)
                          if getattr(m, "metallicFactor", None) is not None else 0.0),
        "roughness": float(getattr(m, "roughnessFactor", None)
                           if getattr(m, "roughnessFactor", None) is not None else 0.5),
        "opacity": opacity,
        "ior": float(getattr(m, "_forge_ior", 1.52 if opacity < 0.99 else 1.5) or 1.5),
        "transmission": float(getattr(m, "_forge_transmission",
                                      max(0.0, 1.0 - opacity) if opacity < 0.99 else 0.0) or 0.0),
        "clearcoat": float(getattr(m, "_forge_clearcoat", 0.0) or 0.0),
        "clearcoat_roughness": float(getattr(m, "_forge_clearcoat_roughness", 0.06) or 0.06),
        "emissive": emis,
        "uv": uv_arr,
        "albedo_tex": albedo_tex,
        "mr_tex": mr_tex,
        "normal_tex": normal_tex,
    }


def _gather(scene: trimesh.Scene):
    """Liste les parties en coordonnées monde : (verts, vnormals, faces, fnormals, smooth, mp)."""
    scene = scene.copy()
    parts = []
    for node in scene.graph.nodes_geometry:
        T, gname = scene.graph[node]
        geom = scene.geometry[gname]
        if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
            continue
        g = geom.copy()
        g.apply_transform(T)
        fn = g.face_normals
        vn = g.vertex_normals
        dots = np.einsum("fkc,fc->fk", vn[g.faces], fn)
        smooth_mask = (dots > 0.72).all(axis=1)
        mp = _material_params(g)
        vc = None
        if getattr(g.visual, "kind", None) == "vertex" and mp["albedo_tex"] is None:
            vca = np.asarray(g.visual.vertex_colors, dtype=float)
            if vca.size:
                if vca.max() > 1.001:
                    vca = vca / 255.0
                vc = vca[:, :3].copy()
                mp["color"] = np.ones(3)
        mp["vcolors"] = vc
        parts.append((g.vertices.copy(), vn.copy(), g.faces.copy(),
                      fn, smooth_mask, mp))
    return parts


# --------------------------------------------------------------------------- #
# Caméra & rasterisation vectorisée par buckets
# --------------------------------------------------------------------------- #

def _look_at(eye, target, up=np.array([0.0, 0.0, 1.0])):
    fwd = target - eye
    fwd = fwd / np.linalg.norm(fwd)
    right = np.cross(fwd, up)
    if np.linalg.norm(right) < 1e-9:
        right = np.array([1.0, 0.0, 0.0])
    right = right / np.linalg.norm(right)
    true_up = np.cross(right, fwd)
    R = np.vstack([right, true_up, -fwd])          # caméra regarde vers -Z
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = -R @ eye
    return M


def _perspective(fov_deg, aspect, near, far):
    f = 1.0 / np.tan(np.radians(fov_deg) / 2)
    M = np.zeros((4, 4))
    M[0, 0] = f / aspect
    M[1, 1] = f
    M[2, 2] = (far + near) / (near - far)
    M[2, 3] = 2 * far * near / (near - far)
    M[3, 2] = -1
    return M


def _bary_fill(px, py, W, H):
    """Rasterisation unitaire (utilisée uniquement pour les très grands triangles)."""
    x0 = max(int(np.floor(px.min())), 0)
    x1 = min(int(np.ceil(px.max())), W - 1)
    y0 = max(int(np.floor(py.min())), 0)
    y1 = min(int(np.ceil(py.max())), H - 1)
    if x1 < x0 or y1 < y0:
        return None
    xs = np.arange(x0, x1 + 1) + 0.5
    ys = np.arange(y0, y1 + 1) + 0.5
    gx, gy = np.meshgrid(xs, ys)
    ax, ay = px[0], py[0]
    bx, by = px[1], py[1]
    cx, cy = px[2], py[2]
    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(den) < 1e-12:
        return None
    w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
    w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
    w2 = 1.0 - w0 - w1
    mask = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
    if not mask.any():
        return None
    return gx[mask].astype(np.int64), gy[mask].astype(np.int64), \
        w0[mask], w1[mask], w2[mask]


def _rasterize_part(px: np.ndarray, py: np.ndarray, depth: np.ndarray,
                    ok: np.ndarray, faces: np.ndarray, W: int, H: int,
                    zbuf: np.ndarray, z_eps: float = 0.0,
                    update_z: bool = True):
    """Rasterise toutes les faces visibles d'une pièce en mode vectorisé par buckets.

    Retourne `(f_ids, xs, ys, w0, w1, w2, d)` pour tous les fragments qui passent
    le test de profondeur courant (`zbuf`).
    """
    valid_f = ok[faces[:, 0]] & ok[faces[:, 1]] & ok[faces[:, 2]]
    f_idx = np.flatnonzero(valid_f)
    if len(f_idx) == 0:
        return None

    ax, bx, cx = px[faces[f_idx, 0]], px[faces[f_idx, 1]], px[faces[f_idx, 2]]
    ay, by, cy = py[faces[f_idx, 0]], py[faces[f_idx, 1]], py[faces[f_idx, 2]]

    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    x0 = np.maximum(np.floor(np.minimum(np.minimum(ax, bx), cx)).astype(np.int64), 0)
    x1 = np.minimum(np.ceil(np.maximum(np.maximum(ax, bx), cx)).astype(np.int64), W - 1)
    y0 = np.maximum(np.floor(np.minimum(np.minimum(ay, by), cy)).astype(np.int64), 0)
    y1 = np.minimum(np.ceil(np.maximum(np.maximum(ay, by), cy)).astype(np.int64), H - 1)

    keep = (np.abs(den) >= 1e-12) & (x1 >= x0) & (y1 >= y0)
    if not keep.any():
        return None

    f_idx = f_idx[keep]
    ax, bx, cx = ax[keep], bx[keep], cx[keep]
    ay, by, cy = ay[keep], by[keep], cy[keep]
    den = den[keep]
    x0, x1, y0, y1 = x0[keep], x1[keep], y0[keep], y1[keep]
    bw = x1 - x0 + 1
    bh = y1 - y0 + 1
    max_side = np.maximum(bw, bh)

    out_f, out_x, out_y, out_w0, out_w1, out_w2, out_d = [], [], [], [], [], [], []
    d0_all = depth[faces[:, 0]]
    d1_all = depth[faces[:, 1]]
    d2_all = depth[faces[:, 2]]

    # 1) Buckets SIMD pour les triangles petits & moyens (98%+ des maillages denses)
    for lo_s, hi_s, chunk in ((0, 8, 2048), (8, 24, 512), (24, 64, 128)):
        sel = np.flatnonzero((max_side > lo_s) & (max_side <= hi_s))
        if len(sel) == 0:
            continue
        ox, oy = np.meshgrid(np.arange(hi_s), np.arange(hi_s))  # (hi_s, hi_s)
        for start in range(0, len(sel), chunk):
            s = sel[start:start + chunk]
            xs_g = x0[s, None, None] + ox[None, :, :]
            ys_g = y0[s, None, None] + oy[None, :, :]
            in_box = (xs_g <= x1[s, None, None]) & (ys_g <= y1[s, None, None])
            gx = xs_g + 0.5
            gy = ys_g + 0.5
            inv_den = 1.0 / den[s, None, None]
            w0 = ((by[s, None, None] - cy[s, None, None]) * (gx - cx[s, None, None])
                  + (cx[s, None, None] - bx[s, None, None]) * (gy - cy[s, None, None])) * inv_den
            w1 = ((cy[s, None, None] - ay[s, None, None]) * (gx - cx[s, None, None])
                  + (ax[s, None, None] - cx[s, None, None]) * (gy - cy[s, None, None])) * inv_den
            w2 = 1.0 - w0 - w1
            hit = in_box & (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not hit.any():
                continue
            bi, rj, ck = np.nonzero(hit)
            fi = f_idx[s[bi]]
            xs_v = xs_g[bi, rj, ck]
            ys_v = ys_g[bi, rj, ck]
            w0_v = w0[bi, rj, ck]
            w1_v = w1[bi, rj, ck]
            w2_v = w2[bi, rj, ck]
            d_v = w0_v * d0_all[fi] + w1_v * d1_all[fi] + w2_v * d2_all[fi]
            vis = d_v < zbuf[ys_v, xs_v] + z_eps
            if not vis.any():
                continue
            fi, xs_v, ys_v = fi[vis], xs_v[vis], ys_v[vis]
            w0_v, w1_v, w2_v, d_v = w0_v[vis], w1_v[vis], w2_v[vis], d_v[vis]
            if update_z:
                np.minimum.at(zbuf, (ys_v, xs_v), d_v)
            out_f.append(fi); out_x.append(xs_v); out_y.append(ys_v)
            out_w0.append(w0_v); out_w1.append(w1_v); out_w2.append(w2_v); out_d.append(d_v)

    # 2) Grands triangles (> 64 px de côté, ex. plateau de table ou mur) : par triangle
    big = np.flatnonzero(max_side > 64)
    for k in big:
        t = int(f_idx[k])
        ia, ib, ic = faces[t]
        filled = _bary_fill(np.array([px[ia], px[ib], px[ic]]),
                            np.array([py[ia], py[ib], py[ic]]), W, H)
        if filled is None:
            continue
        xs_v, ys_v, w0_v, w1_v, w2_v = filled
        d_v = w0_v * depth[ia] + w1_v * depth[ib] + w2_v * depth[ic]
        vis = d_v < zbuf[ys_v, xs_v] + z_eps
        if not vis.any():
            continue
        xs_v, ys_v = xs_v[vis], ys_v[vis]
        w0_v, w1_v, w2_v, d_v = w0_v[vis], w1_v[vis], w2_v[vis], d_v[vis]
        if update_z:
            zbuf[ys_v, xs_v] = np.minimum(zbuf[ys_v, xs_v], d_v)
        out_f.append(np.full(len(xs_v), t, dtype=np.int64))
        out_x.append(xs_v); out_y.append(ys_v)
        out_w0.append(w0_v); out_w1.append(w1_v); out_w2.append(w2_v); out_d.append(d_v)

    if not out_f:
        return None
    return (np.concatenate(out_f), np.concatenate(out_x), np.concatenate(out_y),
            np.concatenate(out_w0), np.concatenate(out_w1),
            np.concatenate(out_w2), np.concatenate(out_d))


def _compute_tangent_frame(verts_cam: np.ndarray, faces: np.ndarray,
                           uv: np.ndarray):
    """Repère tangent `(T_cam, B_cam)` par face pour le normal mapping."""
    p0 = verts_cam[faces[:, 0]]
    p1 = verts_cam[faces[:, 1]]
    p2 = verts_cam[faces[:, 2]]
    uv0 = uv[faces[:, 0]]
    uv1 = uv[faces[:, 1]]
    uv2 = uv[faces[:, 2]]
    dp1 = p1 - p0
    dp2 = p2 - p0
    duv1 = uv1 - uv0
    duv2 = uv2 - uv0
    det = duv1[:, 0] * duv2[:, 1] - duv1[:, 1] * duv2[:, 0]
    inv_det = np.where(np.abs(det) > 1e-10, 1.0 / np.where(np.abs(det) > 1e-10, det, 1.0), 0.0)[:, None]
    T = (dp1 * duv2[:, 1:2] - dp2 * duv1[:, 1:2]) * inv_det
    # L'image normalMap a +Y vers le bas en convention Sobel standard : aligne B
    B = (dp2 * duv1[:, 0:1] - dp1 * duv2[:, 0:1]) * inv_det
    T /= np.clip(np.linalg.norm(T, axis=1, keepdims=True), 1e-9, None)
    B /= np.clip(np.linalg.norm(B, axis=1, keepdims=True), 1e-9, None)
    return T, B


def _srgb_to_linear(c):
    return np.power(np.clip(c, 0.0, 1.0), 2.2)


def _linear_to_srgb(c):
    return np.power(np.clip(c, 0.0, 1.0), 1.0 / 2.2)


def _tone(c):
    """Tone mapping filmique ACES en espace linéaire suivi de l'encodage sRGB."""
    x = np.maximum(c, 0.0)
    mapped = (x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14)
    return _linear_to_srgb(np.clip(mapped, 0.0, 1.0))


def _sample_studio_hdri(dir_w: np.ndarray, rough: np.ndarray) -> np.ndarray:
    """Dôme HDRI studio photographique analytique en espace monde (Z-up) filtré
    par la rugosité `rough` (`(N, 1)`), reproduisant les vraies bandes de réflexion
    d'un plateau produit / automobile :
      - Octabox zénithale chaude principale
      - Strip-box latérale gauche (reflet filant le long des lames / tubes / fourches)
      - Strip-box froide de détourage (rim light bleutée)
      - Cyclorama studio clair au sol + plafond sombre hors boîtes à lumière
        (indispensable au contraste réaliste du chrome et du vernis !).
    """
    dz = dir_w[:, 2:3]
    # Contraste plafond sombre d'atelier / rebond clair du cyclorama au sol
    horizon = 1.0 / (1.0 + np.exp(dz * 7.5))  # 1 vers le sol, 0 vers le plafond
    base = np.array([[0.052, 0.056, 0.068]]) * (1.0 - horizon) + np.array([[0.26, 0.265, 0.28]]) * horizon
    # Fine ligne lumineuse d'horizon studio (signature visuelle du métal poli)
    h_band = np.exp(-((dz + 0.03) / (0.075 + 0.45 * rough)) ** 2) * (1.0 - 0.55 * rough)
    env = base + np.array([[0.34, 0.35, 0.38]]) * h_band

    boxes = (
        # (direction unitaire monde, couleur linéaire HDR, demi-ouverture base)
        (np.array([0.24, -0.28, 0.929]), np.array([[3.40, 3.30, 3.12]]), 0.30),
        (np.array([-0.70, -0.54, 0.467]), np.array([[2.15, 2.08, 1.98]]), 0.22),
        (np.array([0.76, 0.46, 0.459]), np.array([[1.75, 1.96, 2.35]]), 0.20),
    )
    for bdir, bcol, w0 in boxes:
        cos_a = (dir_w * bdir[None, :]).sum(axis=1, keepdims=True)
        ang2 = np.maximum(0.0, 2.0 * (1.0 - np.clip(cos_a, -1.0, 1.0)))
        width = w0 + 1.35 * rough
        # Conservation d'énergie approximative quand le lobe s'élargit avec rough
        energy = (w0 / width) ** 1.35
        env = env + bcol * np.exp(-ang2 / (width ** 2)) * energy
    return env


def _screen_space_ao(zbuf: np.ndarray, radius_world: float, fov_deg: float) -> np.ndarray:
    """Occlusion ambiante écran (SSAO multi-échelles) pure NumPy en ~20 ms :
    compare la profondeur de chaque pixel à sa moyenne locale multi-rayons
    pondérée en espace métrique pour assombrir naturellement creux, passages de
    roues, dessous de selle, ailettes moteur et jonctions d'assemblage."""
    H, W = zbuf.shape
    bg = ~np.isfinite(zbuf)
    if bg.all():
        return np.ones((H, W), dtype=np.float64)
    z_max = float(zbuf[~bg].max())
    z_safe = np.where(bg, z_max + radius_world * 0.6, zbuf)

    occ = np.zeros((H, W), dtype=np.float64)
    scale = max(radius_world * 0.16, 1e-5)
    for sigma, weight in ((2.2, 0.42), (6.5, 0.36), (15.0, 0.22)):
        z_blur = ndimage.gaussian_filter(z_safe, sigma=sigma * (W / 1024.0))
        # Si le pixel est plus loin que son voisinage moyen (`z_safe > z_blur`),
        # il est au fond d'une cavité / angle rentrant -> occlus !
        dz = (z_safe - z_blur) / scale
        occ += weight * np.clip(dz * 2.1, 0.0, 1.0) / (1.0 + np.abs(dz) * 1.4)

    ao = np.clip(1.0 - 0.82 * occ, 0.28, 1.0)
    ao[bg] = 1.0
    return ao


def _ortho(hw: float, hh: float, zn: float, zf: float) -> np.ndarray:
    M = np.zeros((4, 4), dtype=np.float64)
    M[0, 0] = 1.0 / max(hw, 1e-6)
    M[1, 1] = 1.0 / max(hh, 1e-6)
    M[2, 2] = -2.0 / max(zf - zn, 1e-6)
    M[2, 3] = -(zf + zn) / max(zf - zn, 1e-6)
    M[3, 3] = 1.0
    return M


def _build_shadow_map(parts, opaque_indices, center: np.ndarray, radius: float,
                      l_world: np.ndarray, smap_size: int = 512):
    """Construit en ~12 ms un shadow-buffer directionnel orthographique depuis la
    key light `l_world` : projette de vraies ombres portées 3D d'une pièce sur
    l'autre (garde-boue sur pneu, selle sur amortisseur, garde sur poignée)."""
    up = np.array([0.0, 0.0, 1.0]) if abs(l_world[2]) < 0.92 else np.array([0.0, 1.0, 0.0])
    V_l = _look_at(center + l_world * (radius * 3.0), center, up=up)
    span = radius * 1.18
    P_l = _ortho(span, span, radius * 0.2, radius * 6.0)
    PV_l = P_l @ V_l
    sbuf = np.full((smap_size, smap_size), np.inf, dtype=np.float64)
    for pi in opaque_indices:
        verts, _, faces, _, _, _ = parts[pi]
        vw = np.hstack([verts, np.ones((len(verts), 1))])
        clip = (PV_l @ vw.T).T
        px = (clip[:, 0] * 0.5 + 0.5) * smap_size
        py = (1.0 - (clip[:, 1] * 0.5 + 0.5)) * smap_size
        lz = (clip[:, 2] * 0.5 + 0.5)
        ok = np.ones(len(verts), dtype=bool)
        _rasterize_part(px, py, lz, ok, faces, smap_size, smap_size, sbuf, update_z=True)
    return PV_l, sbuf


def _shadow_visibility(pos_w: np.ndarray, PV_l: np.ndarray,
                       sbuf: np.ndarray) -> np.ndarray:
    """Filtrage doux PCF 5 prises sur le shadow-buffer 3D."""
    S = sbuf.shape[0]
    pw = np.hstack([pos_w, np.ones((len(pos_w), 1))])
    clip = (PV_l @ pw.T).T
    fx = (clip[:, 0] * 0.5 + 0.5) * S
    fy = (1.0 - (clip[:, 1] * 0.5 + 0.5)) * S
    lz = clip[:, 2] * 0.5 + 0.5
    bias = 0.0045
    vis = np.zeros(len(pos_w), dtype=np.float64)
    for dx, dy in ((0.0, 0.0), (-1.2, -0.6), (1.2, -0.6), (-0.6, 1.2), (0.6, 1.2)):
        ix = np.clip(np.round(fx + dx - 0.5).astype(np.int64), 0, S - 1)
        iy = np.clip(np.round(fy + dy - 0.5).astype(np.int64), 0, S - 1)
        vis += (lz <= sbuf[iy, ix] + bias).astype(np.float64)
    return vis * 0.2


def _shade_fragments(fi, w0, w1, w2, depth, verts_cam, vn_cam, fn_cam,
                     smooth_mask, faces, mp, lights, Rv=None,
                     ssao_px=None, shadow_ctx=None, verts_world=None,
                     floor_ao=None, ground_z=None, height_span=None):
    """Shading PBR physique Cook-Torrance GGX + dôme HDRI studio + AO cuite &
    SSAO + auto-ombrage directionnel 3D PCF en espace linéaire."""
    ia = faces[fi, 0]
    ib = faces[fi, 1]
    ic = faces[fi, 2]

    # Position exacte en espace caméra -> vrai vecteur vue perspectif V par pixel !
    pos_cam = (w0[:, None] * verts_cam[ia]
               + w1[:, None] * verts_cam[ib]
               + w2[:, None] * verts_cam[ic])
    V_vec = -pos_cam / np.clip(np.linalg.norm(pos_cam, axis=1, keepdims=True), 1e-9, None)

    n_smooth = (w0[:, None] * vn_cam[ia] + w1[:, None] * vn_cam[ib]
                + w2[:, None] * vn_cam[ic])
    n = np.where(smooth_mask[fi, None], n_smooth, fn_cam[fi])
    n /= np.clip(np.linalg.norm(n, axis=1, keepdims=True), 1e-9, None)
    # Double-sided cohérent avec glTF `doubleSided=True`
    flip = (n * V_vec).sum(axis=1, keepdims=True) < 0.0
    n = np.where(flip, -n, n)

    albedo_srgb = mp["color"]
    vcols = mp.get("vcolors")
    uv_arr = mp.get("uv")
    albedo_tex = mp.get("albedo_tex")
    mr_tex = mp.get("mr_tex")
    normal_tex = mp.get("normal_tex")

    metal = mp["metallic"]
    rough = mp["roughness"]
    ao_baked = np.ones(len(fi), dtype=np.float64)

    if uv_arr is not None and (albedo_tex is not None or mr_tex is not None
                               or normal_tex is not None):
        iz0 = w0 / np.clip(depth[ia], 1e-6, None)
        iz1 = w1 / np.clip(depth[ib], 1e-6, None)
        iz2 = w2 / np.clip(depth[ic], 1e-6, None)
        inv_s = 1.0 / np.clip(iz0 + iz1 + iz2, 1e-12, None)
        pw0, pw1, pw2 = iz0 * inv_s, iz1 * inv_s, iz2 * inv_s
        uv_px = (pw0[:, None] * uv_arr[ia]
                 + pw1[:, None] * uv_arr[ib]
                 + pw2[:, None] * uv_arr[ic])

        if albedo_tex is not None:
            albedo_srgb = _sample_tex_bilinear(albedo_tex, uv_px) * mp["color"][None, :]
        if mr_tex is not None:
            mr_val = _sample_tex_bilinear(mr_tex, uv_px)
            # glTF 2.0 ORM : canal R = Occlusion (AO), G = Roughness, B = Metallic
            ao_baked = np.clip(mr_val[:, 0], 0.12, 1.0)
            rough = np.clip(mr_val[:, 1] * rough, 0.04, 1.0)
            metal = np.clip(mr_val[:, 2] * metal, 0.0, 1.0)
        if normal_tex is not None and mp.get("_tangent_cam") is not None:
            T_cam, B_cam = mp["_tangent_cam"]
            ts_n = _sample_tex_bilinear(normal_tex, uv_px)
            n = (ts_n[:, 0:1] * T_cam[fi]
                 + ts_n[:, 1:2] * B_cam[fi]
                 + ts_n[:, 2:3] * n)
            n /= np.clip(np.linalg.norm(n, axis=1, keepdims=True), 1e-9, None)
    elif vcols is not None:
        albedo_srgb = (w0[:, None] * vcols[ia] + w1[:, None] * vcols[ib]
                       + w2[:, None] * vcols[ic])

    if np.ndim(albedo_srgb) == 1:
        albedo_srgb = np.broadcast_to(albedo_srgb[None, :], (len(fi), 3))
    albedo = _srgb_to_linear(albedo_srgb)

    metal_c = metal[:, None] if np.ndim(metal) == 1 else np.full((len(fi), 1), float(metal))
    rough_c = np.clip(rough[:, None] if np.ndim(rough) == 1 else np.full((len(fi), 1), float(rough)),
                      0.045, 1.0)
    ao = ao_baked[:, None]
    if ssao_px is not None:
        ao = ao * ssao_px[:, None]

    # Auto-ombrage 3D sur la key light
    key_vis = np.ones((len(fi), 1), dtype=np.float64)
    if shadow_ctx is not None and verts_world is not None:
        PV_l, sbuf = shadow_ctx
        pos_w = (w0[:, None] * verts_world[ia]
                 + w1[:, None] * verts_world[ib]
                 + w2[:, None] * verts_world[ic])
        key_vis = (0.28 + 0.72 * _shadow_visibility(pos_w, PV_l, sbuf))[:, None]

    # BRDF microfacettes Cook-Torrance GGX exacte
    alpha = rough_c ** 2
    alpha2 = alpha ** 2
    ndv = np.clip((n * V_vec).sum(axis=1, keepdims=True), 1e-4, 1.0)
    F0 = 0.04 * (1.0 - metal_c) + albedo * metal_c
    k_g = ((rough_c + 1.0) ** 2) * 0.125
    g1_v = ndv / (ndv * (1.0 - k_g) + k_g)

    L_key, L_fill, L_rim, _ = lights
    light_defs = (
        (L_key,  np.array([[3.05, 2.96, 2.82]]), key_vis),
        (L_fill, np.array([[0.72, 0.80, 0.95]]), 1.0),
        (L_rim,  np.array([[1.55, 1.66, 1.88]]), 1.0),
    )

    lo = np.zeros((len(fi), 3), dtype=np.float64)
    for L_dir, l_rad, vis_l in light_defs:
        L = L_dir / max(np.linalg.norm(L_dir), 1e-9)
        ndl = np.clip((n * L[None, :]).sum(axis=1, keepdims=True), 0.0, 1.0)
        H_vec = L[None, :] + V_vec
        H_vec /= np.clip(np.linalg.norm(H_vec, axis=1, keepdims=True), 1e-9, None)
        ndh = np.clip((n * H_vec).sum(axis=1, keepdims=True), 0.0, 1.0)
        vdh = np.clip((V_vec * H_vec).sum(axis=1, keepdims=True), 0.0, 1.0)

        denom_d = ndh * ndh * (alpha2 - 1.0) + 1.0
        D = alpha2 / (math.pi * denom_d * denom_d + 1e-9)
        g1_l = ndl / (ndl * (1.0 - k_g) + k_g + 1e-9)
        G = g1_v * g1_l
        F = F0 + (1.0 - F0) * ((1.0 - vdh) ** 5)

        spec = (D * G * F) / np.clip(4.0 * ndv * ndl, 1e-5, None)
        k_d = (1.0 - F) * (1.0 - metal_c)
        lo += (k_d * albedo / math.pi + spec) * l_rad * ndl * vis_l

    # Illumination basée sur l'image (IBL) via le dôme HDRI studio en espace monde
    R_cam = 2.0 * ndv * n - V_vec
    if Rv is not None:
        R_w = R_cam @ Rv          # Rv transpose camera -> world (car v_cam = v_w @ Rv.T)
        N_w = n @ Rv
    else:
        R_w, N_w = R_cam, n

    env_spec = _sample_studio_hdri(R_w, rough_c)
    env_diff = _sample_studio_hdri(N_w, np.ones_like(rough_c) * 0.92)
    F_env = F0 + (np.maximum(1.0 - rough_c, F0) - F0) * ((1.0 - ndv) ** 5)
    # Occlusion spéculaire physique (Lagarde / Frostbite) : évite les reflets
    # chromés parasites au fond des cavités sombres tout en les gardant vifs dehors
    spec_ao = np.clip(np.power(ndv + ao, alpha) - 1.0 + ao, 0.0, 1.0)

    # v5.6 — occultation d'environnement par le sol : près du contact, le dôme
    # HDRI est masqué par le cyclorama. Sans ça, un objet long et fin (katana)
    # baigne dans un environnement uniforme et paraît plat et blanc.
    if ground_z is not None and height_span:
        # Hauteur relative au sol : plus le fragment est bas, plus le cyclorama
        # masque l'environnement (occlusion d'environnement directionnelle).
        pos_w_f = (w0[:, None] * verts_world[ia]
                   + w1[:, None] * verts_world[ib]
                   + w2[:, None] * verts_world[ic])
        z_rel = np.clip((pos_w_f[:, 2:3] - ground_z) / max(height_span, 1e-6), 0.0, 1.0)
        env_occ = 1.0 - 0.55 * np.exp(-z_rel / 0.11)
        ao = ao * np.clip(env_occ, 0.35, 1.0)
        spec_ao = spec_ao * np.clip(env_occ, 0.35, 1.0)
    elif floor_ao is not None:
        ao = ao * floor_ao
        spec_ao = spec_ao * floor_ao

    ibl = (albedo * (1.0 - metal_c) * env_diff * 0.34 * ao
           + env_spec * F_env * (1.0 - 0.32 * rough_c) * spec_ao)

    # Couche supérieure Clearcoat vernis automobile / céramique émaillée (IOR=1.5 -> F0=0.04)
    cc = float(mp.get("clearcoat", 0.0))
    cc_lin = 0.0
    if cc > 0.001:
        cc_r = max(float(mp.get("clearcoat_roughness", 0.06)), 0.03)
        a_cc = cc_r ** 2
        a2_cc = a_cc ** 2
        F_cc = 0.04 + 0.96 * ((1.0 - ndv) ** 5)
        env_cc = _sample_studio_hdri(R_w, np.full_like(rough_c, cc_r))
        L_key_n = L_key / max(np.linalg.norm(L_key), 1e-9)
        H_cc = L_key_n[None, :] + V_vec
        H_cc /= np.clip(np.linalg.norm(H_cc, axis=1, keepdims=True), 1e-9, None)
        ndh_cc = np.clip((n * H_cc).sum(axis=1, keepdims=True), 0.0, 1.0)
        dd_cc = ndh_cc * ndh_cc * (a2_cc - 1.0) + 1.0
        spec_cc = (a2_cc / (math.pi * dd_cc * dd_cc + 1e-9)) * 0.06 * key_vis
        cc_lin = cc * F_cc * (env_cc * spec_ao + spec_cc * 2.6)

    # v5.6 — l'émission était clippée à [0,1] par `_srgb_to_linear`, ce qui
    # détruisait l'intensité HDR (`mk.mat.emissive("#3af0ff", 2.6)` -> 2.6).
    # On sépare la chromaticité (bornée) de l'intensité (conservée en HDR) pour
    # que le néon dépasse réellement le seuil de bloom.
    em_raw = np.asarray(mp["emissive"], dtype=float)
    if float(np.max(em_raw)) > 0.0:
        peak = float(np.max(em_raw))
        chroma = np.clip(em_raw / peak, 0.0, 1.0)
        emissive_lin = _srgb_to_linear(chroma) * (peak ** 0.85) * 1.35
    else:
        emissive_lin = 0.0
    return _tone((lo * (0.35 + 0.65 * ao) + ibl + cc_lin + emissive_lin) * 1.06)


def _post_finish(img: Image.Image, bloom: bool = True, vignette: bool = True,
                 sharpen: bool = True) -> Image.Image:
    """Finition photo de la sortie de rendu (v5.6).

    Le shading PBR est correct mais l'image sortait « plate » : pas de halo sur
    les émissions, coins aussi lumineux que le sujet, micro-détail écrasé par le
    downscale. Trois retouches standard de plateau produit, toutes mesurables :
      - bloom émissif : seuil de luminance + flou gaussien -> le néon respire ;
      - vignettage doux : recentre le regard (10 % max dans les coins) ;
      - unsharp mask : récupère le détail perdu par le LANCZOS final.
    """
    arr = np.asarray(img, dtype=np.float32) / 255.0
    H, W = arr.shape[:2]

    if bloom:
        lum = arr @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        mask = np.clip((lum - 0.70) / 0.26, 0.0, 1.0)[..., None] ** 1.2
        bright = arr * mask
        small = Image.fromarray((np.clip(bright, 0, 1) * 255).astype(np.uint8))
        sw, sh = max(32, W // 4), max(32, H // 4)
        small = small.resize((sw, sh), Image.BILINEAR).filter(
            ImageFilter.GaussianBlur(radius=max(2.0, sw / 28.0)))
        halo = np.asarray(small.resize((W, H), Image.BILINEAR), dtype=np.float32) / 255.0
        arr = 1.0 - (1.0 - arr) * (1.0 - 0.75 * halo)   # écran additif doux

    if vignette:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        arr *= (1.0 - 0.10 * np.clip((r - 0.55) / 0.75, 0.0, 1.0) ** 2)[..., None]

    out = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    if sharpen:
        out = out.filter(ImageFilter.UnsharpMask(radius=1.4, percent=65, threshold=2))
    return out


def render_view(scene: trimesh.Scene, azimuth_deg=42.0, elevation_deg=22.0,
                size=1024, fov=38.0, ssaa=2, shadow=True, post=True) -> Image.Image:
    parts = _gather(scene)
    if not parts:
        raise ValueError("scène vide")

    W = H = int(size * ssaa)
    all_v = np.vstack([p[0] for p in parts])
    lo, hi = all_v.min(0), all_v.max(0)
    center = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo) / 2) + 1e-6

    eye = center + radius * 3.1 * np.array([
        np.sin(np.radians(azimuth_deg)) * np.cos(np.radians(elevation_deg)),
        -np.cos(np.radians(azimuth_deg)) * np.cos(np.radians(elevation_deg)),
        np.sin(np.radians(elevation_deg))])
    near, far = radius * 0.1, radius * 12
    V = _look_at(eye, center)
    P = _perspective(fov, W / H, near, far)
    PV = P @ V

    L_key = np.array([0.35, 0.45, 0.83]); L_key /= np.linalg.norm(L_key)
    L_fill = np.array([-0.62, 0.18, 0.55]); L_fill /= np.linalg.norm(L_fill)
    L_rim = np.array([0.05, -0.72, 0.25]); L_rim /= np.linalg.norm(L_rim)
    # v5.6 — key/fill ratio augmenté (1.05/0.38 -> 1.35/0.26) : la separation
    # plan clair / plan sombre est ce qui distingue un rendu produit d'une
    # image plate ; l'IBL ambiante est réduite d'autant pour ne pas compenser.
    I = np.array([1.35, 0.26, 0.46])
    lights = (L_key, L_fill, L_rim, I)

    img = np.zeros((H, W, 3))
    zbuf = np.full((H, W), np.inf)

    # ---- fond dégradé studio ----
    grad = np.linspace(0, 1, H)[:, None, None]
    img[:] = (BG_TOP * (1 - grad) + BG_BOTTOM * grad) * np.ones((1, W, 1))

    # ---- ombre de contact : projection C via PIL.ImageDraw + flou Gaussien ----
    if shadow:
        floor_z = lo[2]
        SW = max(256, int(size))
        sh_im = Image.new("L", (SW, SW), 0)
        dr = ImageDraw.Draw(sh_im)
        for verts, _, faces, _, _, _p in parts:
            vf = verts.copy()
            vf[:, 2] = floor_z
            clip_s = (PV @ np.hstack([vf, np.ones((len(vf), 1))]).T).T
            ok_s = clip_s[:, 3] > 1e-6
            ws = np.clip(clip_s[:, 3:4], 1e-9, None)
            ndc_s = clip_s[:, :3] / ws
            sx = (ndc_s[:, 0] * 0.5 + 0.5) * SW
            sy = (1.0 - (ndc_s[:, 1] * 0.5 + 0.5)) * SW
            vf_ok = ok_s[faces[:, 0]] & ok_s[faces[:, 1]] & ok_s[faces[:, 2]]
            pts = np.stack([sx[faces[vf_ok]], sy[faces[vf_ok]]], axis=-1)
            for tri in pts.tolist():
                dr.polygon([(tri[0][0], tri[0][1]),
                            (tri[1][0], tri[1][1]),
                            (tri[2][0], tri[2][1])], fill=255)
        # Deux couches : halo large (occlusion ambiante au sol) + noyau serré
        # (contact réel) — sans le noyau, l'objet « flotte » sur le fond.
        halo_im = sh_im.filter(ImageFilter.GaussianBlur(radius=max(2, SW // 70)))
        core_im = sh_im.filter(ImageFilter.GaussianBlur(radius=max(1, SW // 220)))
        if SW != W:
            halo_im = halo_im.resize((W, H), Image.BILINEAR)
            core_im = core_im.resize((W, H), Image.BILINEAR)
        halo = np.asarray(halo_im, dtype=float) / 255.0
        core = np.asarray(core_im, dtype=float) / 255.0
        img *= (1.0 - 0.34 * halo[..., None]) * (1.0 - 0.30 * core[..., None])

    # ---- 1) Passe OPAQUE différée : rasterisation z-buffer -> shading unique ----
    opaque_indices = [i for i in range(len(parts)) if parts[i][5]["opacity"] >= 0.999]
    glass_indices = [i for i in range(len(parts)) if parts[i][5]["opacity"] < 0.999]

    opaque_records = []
    Rv = V[:3, :3]
    for pi in opaque_indices:
        verts, vn, faces, fn, smooth_mask, mp = parts[pi]
        vw = np.hstack([verts, np.ones((len(verts), 1))])
        clip = (PV @ vw.T).T
        w_clip = clip[:, 3]
        ok = w_clip > 1e-6
        ndc = clip[:, :3] / np.clip(w_clip[:, None], 1e-9, None)
        px = (ndc[:, 0] * 0.5 + 0.5) * W
        py = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * H
        depth = w_clip.copy()

        res = _rasterize_part(px, py, depth, ok, faces, W, H, zbuf,
                              z_eps=0.0, update_z=True)
        if res is None:
            continue
        verts_cam = (V @ vw.T).T[:, :3]
        vn_cam = vn @ Rv.T
        fn_cam = fn @ Rv.T
        if mp.get("uv") is not None and mp.get("normal_tex") is not None:
            mp["_tangent_cam"] = _compute_tangent_frame(verts_cam, faces, mp["uv"])
        opaque_records.append((res, depth, verts, verts_cam, vn_cam, fn_cam,
                               smooth_mask, faces, mp))

    # SSAO écran multi-échelles + Shadow-Map 3D directionnelle de la key light
    ssao_buf = _screen_space_ao(zbuf, radius, fov)
    shadow_ctx = None
    if shadow and opaque_indices:
        l_key_world = lights[0] @ Rv
        l_key_world /= max(np.linalg.norm(l_key_world), 1e-9)
        shadow_ctx = _build_shadow_map(parts, opaque_indices, center, radius, l_key_world)

    # Ne shade QUE les fragments qui ont gagné le z-buffer final !
    for (fi, xs, ys, w0, w1, w2, d), depth, verts_w, verts_cam, vn_cam, fn_cam, smooth_mask, faces, mp in opaque_records:
        win = d <= zbuf[ys, xs] + 1e-12
        if not win.any():
            continue
        fi, xs, ys = fi[win], xs[win], ys[win]
        w0, w1, w2, d = w0[win], w1[win], w2[win], d[win]
        col = _shade_fragments(fi, w0, w1, w2, depth, verts_cam, vn_cam, fn_cam,
                               smooth_mask, faces, mp, lights, Rv=Rv,
                               ssao_px=ssao_buf[ys, xs], shadow_ctx=shadow_ctx,
                               verts_world=verts_w,
                               ground_z=float(lo[2]),
                               height_span=float(max(hi[2] - lo[2], 1e-6)))
        img[ys, xs] = col

    # ---- 2) Passe VERRE RÉFRACTIF PHYSIQUE (Snell + Beer-Lambert + Fresnel + Specular pur) ----
    for pi in glass_indices:
        verts, vn, faces, fn, smooth_mask, mp = parts[pi]
        vw = np.hstack([verts, np.ones((len(verts), 1))])
        clip = (PV @ vw.T).T
        w_clip = clip[:, 3]
        ok = w_clip > 1e-6
        ndc = clip[:, :3] / np.clip(w_clip[:, None], 1e-9, None)
        px = (ndc[:, 0] * 0.5 + 0.5) * W
        py = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * H
        depth = w_clip.copy()

        res = _rasterize_part(px, py, depth, ok, faces, W, H, zbuf,
                              z_eps=1e-5, update_z=False)
        if res is None:
            continue
        fi, xs, ys, w0, w1, w2, d = res
        verts_cam = (V @ vw.T).T[:, :3]
        vn_cam = vn @ Rv.T
        fn_cam = fn @ Rv.T

        ia, ib, ic = faces[fi, 0], faces[fi, 1], faces[fi, 2]
        pos_cam = w0[:, None] * verts_cam[ia] + w1[:, None] * verts_cam[ib] + w2[:, None] * verts_cam[ic]
        V_vec = -pos_cam / np.clip(np.linalg.norm(pos_cam, axis=1, keepdims=True), 1e-9, None)
        n_sm = w0[:, None] * vn_cam[ia] + w1[:, None] * vn_cam[ib] + w2[:, None] * vn_cam[ic]
        n = np.where(smooth_mask[fi, None], n_sm, fn_cam[fi])
        n /= np.clip(np.linalg.norm(n, axis=1, keepdims=True), 1e-9, None)
        n = np.where((n * V_vec).sum(axis=1, keepdims=True) < 0.0, -n, n)

        ior = float(mp.get("ior", 1.52))
        r0 = ((1.0 - ior) / (1.0 + ior)) ** 2
        ndv = np.clip((n * V_vec).sum(axis=1, keepdims=True), 0.001, 1.0)
        fres = r0 + (1.0 - r0) * ((1.0 - ndv) ** 5)  # bord de verre brillant réaliste !
        rough_g = max(float(mp.get("roughness", 0.045)), 0.035)
        rc_arr = np.full((len(fi), 1), rough_g)

        # Réflexion miroir HDRI + spéculaire GGX NON atténué par l'opacité !
        R_w = (2.0 * ndv * n - V_vec) @ Rv
        env_refl = _sample_studio_hdri(R_w, rc_arr)
        spec_glint = np.zeros((len(fi), 3), dtype=np.float64)
        a2_g = (rough_g ** 2) ** 2
        for L_dir, l_rad in ((lights[0], np.array([[3.4, 3.3, 3.2]])),
                             (lights[2], np.array([[1.9, 2.05, 2.35]]))):
            Ln = L_dir / max(np.linalg.norm(L_dir), 1e-9)
            Hg = Ln[None, :] + V_vec
            Hg /= np.clip(np.linalg.norm(Hg, axis=1, keepdims=True), 1e-9, None)
            ndh_g = np.clip((n * Hg).sum(axis=1, keepdims=True), 0.0, 1.0)
            dd_g = ndh_g * ndh_g * (a2_g - 1.0) + 1.0
            spec_glint += l_rad * (a2_g / (math.pi * dd_g * dd_g + 1e-9)) * 0.045
        refl_srgb = _tone((env_refl * fres + spec_glint) * 1.06)

        # Radiométrie cristal 100 % LINÉAIRE : réflexion interne totale (TIR) sombre aux bords courbes
        # + transmission Beer-Lambert + reflet HDRI Fresnel + éclats spéculaires GGX purs !
        tint_lin = np.clip(_srgb_to_linear(mp["color"]), 0.04, 1.0)
        density = 0.30 + 0.85 * float(mp["opacity"])
        opt_depth = density * (0.45 + 1.45 * (1.0 - ndv))
        beer = np.power(tint_lin[None, :], opt_depth)
        tir_atten = 1.0 - 0.62 * ((1.0 - ndv) ** 1.85)   # contour optique sombre du cristal sur fond clair !

        disp_px = (ior - 1.0) * 0.048 * W
        rx_off = (-n[:, 0] * disp_px).astype(np.int64)
        ry_off = (n[:, 1] * disp_px).astype(np.int64)

        order = np.argsort(-d, kind="mergesort")
        xs, ys = xs[order], ys[order]
        rx_off, ry_off = rx_off[order], ry_off[order]
        beer, fres, tir_atten = beer[order], fres[order], tir_atten[order]
        refl_lin = env_refl[order] * fres + spec_glint[order]

        spec_o = spec_glint[order]

        flat = ys * W + xs
        while len(flat) > 0:
            _, idx = np.unique(flat, return_index=True)
            xi, yi = xs[idx], ys[idx]
            sx = np.clip(xi + rx_off[idx], 0, W - 1)
            sy = np.clip(yi + ry_off[idx], 0, H - 1)
            bg_lin = _srgb_to_linear(img[sy, sx])
            L_glass = bg_lin * beer[idx] * tir_atten[idx] * (1.0 - fres[idx]) + refl_lin[idx]
            img[yi, xi] = _linear_to_srgb(np.clip(L_glass, 0.0, 1.0) * 0.92 + 0.08 * np.clip(spec_o[idx], 0.0, 2.0))
            rem = np.ones(len(flat), dtype=bool)
            rem[idx] = False
            flat = flat[rem]
            xs, ys = xs[rem], ys[rem]
            rx_off, ry_off = rx_off[rem], ry_off[rem]
            beer, fres, tir_atten = beer[rem], fres[rem], tir_atten[rem]
            refl_lin, spec_o = refl_lin[rem], spec_o[rem]

    out = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    out = out.resize((int(size), int(size)), Image.LANCZOS)
    return _post_finish(out) if post else out


def render_views(scene, outdir, stem, views=None, size=1024, prefix="") -> list:
    """Rend les vues demandées (noms de DEFAULT_VIEWS) → PNG. Retourne les chemins."""
    os.makedirs(outdir, exist_ok=True)
    views = views or ["front", "three_quarter", "top"]
    paths = []
    for v in views:
        if v not in DEFAULT_VIEWS:
            raise ValueError(f"vue inconnue: {v}. disponibles: {list(DEFAULT_VIEWS)}")
        az, el = DEFAULT_VIEWS[v]
        img = render_view(scene, az, el, size=size)
        path = os.path.join(outdir, f"{prefix}{stem}_{v}.png")
        img.save(path)
        paths.append(path)
    return paths


# --------------------------------------------------------------------------- #
# Photos de toutes les faces + turntable (livraison "Meshy-like" complète)
# --------------------------------------------------------------------------- #

def contact_sheet(cells, cols=3, pad=10, bg=(24, 24, 28), out_path=None,
                  title=None, title_h=46):
    """Assemble une planche contact : cells = [(PIL.Image, label), ...]."""
    if not cells:
        raise ValueError("aucune cellule pour la planche contact")
    cw = max(im.width for im, _ in cells)
    ch = max(im.height for im, _ in cells) + 26
    n = len(cells)
    rows = math.ceil(n / cols)
    W = cols * cw + (cols + 1) * pad
    H = rows * ch + (rows + 1) * pad + (title_h if title else 0)

    sheet = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(sheet)
    if title:
        f_t = _font(int(title_h * 0.5))
        tw = draw.textlength(title, font=f_t)
        draw.text(((W - tw) / 2, (title_h - title_h * 0.5) / 2), title,
                  fill=(235, 235, 240), font=f_t)

    for i, (im, label) in enumerate(cells):
        r, c = divmod(i, cols)
        x = pad + c * (cw + pad) + (cw - im.width) // 2
        y = pad + (title_h if title else 0) + r * (ch + pad)
        sheet.paste(im, (x, y))
        f_l = _font(16)
        lw = draw.textlength(label, font=f_l)
        draw.text((x + (im.width - lw) / 2, y + im.height + 4), label,
                  fill=(200, 200, 210), font=f_l)
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        sheet.save(out_path)
    return sheet


def _font(px=16):
    """Police truetype si disponible, sinon défaut PIL."""
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except Exception:
            continue
    try:
        return ImageFont.load_default(px)
    except TypeError:
        return ImageFont.load_default()


def make_gif(paths, out_path, fps=8) -> str:
    """Assemble une liste de PNG en GIF animé (turntable livrable en chat/README)."""
    ims = [Image.open(p).convert("RGB") for p in paths]
    if not ims:
        raise ValueError("aucune image pour le GIF")
    ims[0].save(out_path, save_all=True, append_images=ims[1:],
                duration=int(1000 / fps), loop=0, optimize=True)
    return str(out_path)


def render_all_faces(scene, outdir, stem, size=768, prefix="",
                     make_sheet=True):
    """Photos des 6 faces canoniques (face/dos/gauche/droite/dessus/dessous)."""
    os.makedirs(outdir, exist_ok=True)
    paths, cells = [], []
    for label, az, el in ALL_FACES:
        img = render_view(scene, az, el, size=size)
        p = os.path.join(outdir, f"{prefix}{stem}_face_{label}.png")
        img.save(p)
        paths.append(p)
        if make_sheet:
            cells.append((img, label))
    sheet = None
    if make_sheet:
        sheet = os.path.join(outdir, f"{prefix}{stem}_all_faces.png")
        contact_sheet(cells, cols=3, out_path=sheet,
                      title=f"3d-forge — toutes les faces : {stem}")
    return paths, sheet


def render_turntable(scene, outdir, stem, n=8, size=640, elevation=22.0,
                     prefix="", make_sheet=True):
    """Turntable : n rendus équirépartis en azimuth (+ planche contact)."""
    os.makedirs(outdir, exist_ok=True)
    paths, cells = [], []
    for i in range(n):
        az = 360.0 * i / n
        img = render_view(scene, az, elevation, size=size)
        p = os.path.join(outdir, f"{prefix}{stem}_turn_{i:02d}.png")
        img.save(p)
        paths.append(p)
        if make_sheet:
            cells.append((img, f"az {az:.0f}°"))
    sheet = None
    if make_sheet:
        sheet = os.path.join(outdir, f"{prefix}{stem}_turntable.png")
        contact_sheet(cells, cols=min(4, n), out_path=sheet,
                      title=f"turntable {n} vues — {stem}")
    return paths, sheet


def _bounds(parts):
    all_v = np.vstack([p[0] for p in parts])
    lo, hi = all_v.min(0), all_v.max(0)
    center = (lo + hi) / 2.0
    radius = float(np.linalg.norm(hi - lo) / 2.0) + 1e-6
    return center, radius, (lo, hi)


def _render_gbuffer(scene: trimesh.Scene, azimuth_deg=42.0, elevation_deg=22.0,
                    size=1024, fov=38.0):
    """Extrait `(mask, depth_norm, normal_cam)` exacts à la résolution `size`
    alignés au pixel près sur `render_view`."""
    parts = _gather(scene)
    W = H = int(size)
    if not parts:
        return (np.zeros((H, W), dtype=bool),
                np.zeros((H, W), dtype=np.float64),
                np.zeros((H, W, 3), dtype=np.float64))
    center, radius, _ = _bounds(parts)
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    eye = center + radius * 3.1 * np.array([
        math.sin(az) * math.cos(el),
        -math.cos(az) * math.cos(el),
        math.sin(el),
    ])
    V = _look_at(eye, center)
    P = _perspective(fov, 1.0, radius * 0.1, radius * 12.0)
    PV = P @ V
    Rv = V[:3, :3]

    zbuf = np.full((H, W), np.inf, dtype=np.float64)
    nbuf = np.zeros((H, W, 3), dtype=np.float64)
    recs = []
    for verts, vn, faces, fn, smooth_mask, _ in parts:
        vw = np.hstack([verts, np.ones((len(verts), 1))])
        clip = (PV @ vw.T).T
        wc = clip[:, 3]
        ok = wc > 1e-6
        ndc = clip[:, :3] / np.clip(wc[:, None], 1e-9, None)
        px = (ndc[:, 0] * 0.5 + 0.5) * W
        py = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * H
        res = _rasterize_part(px, py, wc.copy(), ok, faces, W, H, zbuf, update_z=True)
        if res is not None:
            recs.append((res, vn @ Rv.T, fn @ Rv.T, smooth_mask, faces))

    for (fi, xs, ys, w0, w1, w2, d), vn_cam, fn_cam, smooth_mask, faces in recs:
        win = d <= zbuf[ys, xs] + 1e-12
        if not win.any():
            continue
        fi, xs, ys = fi[win], xs[win], ys[win]
        w0, w1, w2 = w0[win], w1[win], w2[win]
        ia, ib, ic = faces[fi, 0], faces[fi, 1], faces[fi, 2]
        ns = w0[:, None] * vn_cam[ia] + w1[:, None] * vn_cam[ib] + w2[:, None] * vn_cam[ic]
        n = np.where(smooth_mask[fi, None], ns, fn_cam[fi])
        n /= np.clip(np.linalg.norm(n, axis=1, keepdims=True), 1e-9, None)
        nbuf[ys, xs] = n

    mask = np.isfinite(zbuf)
    dnorm = np.zeros((H, W), dtype=np.float64)
    if mask.any():
        z0, z1 = float(zbuf[mask].min()), float(zbuf[mask].max())
        # Blanc = proche caméra, noir = loin (convention MiDaS / Depth-ControlNet)
        dnorm[mask] = 1.0 - (zbuf[mask] - z0) / max(z1 - z0, 1e-6)
    return mask, dnorm, nbuf


def render_silhouette(scene: trimesh.Scene, azimuth_deg=42.0, elevation_deg=22.0,
                      size=1024, fov=38.0) -> Image.Image:
    mask, _, _ = _render_gbuffer(scene, azimuth_deg, elevation_deg, size=size, fov=fov)
    return Image.fromarray((mask.astype(np.uint8)) * 255, mode="L")


def render_depth(scene: trimesh.Scene, azimuth_deg=42.0, elevation_deg=22.0,
                 size=1024, fov=38.0) -> Image.Image:
    _, dnorm, _ = _render_gbuffer(scene, azimuth_deg, elevation_deg, size=size, fov=fov)
    return Image.fromarray((np.clip(dnorm, 0.0, 1.0) * 255).astype(np.uint8), mode="L")


def render_normals(scene: trimesh.Scene, azimuth_deg=42.0, elevation_deg=22.0,
                   size=1024, fov=38.0) -> Image.Image:
    mask, _, nbuf = _render_gbuffer(scene, azimuth_deg, elevation_deg, size=size, fov=fov)
    rgb = np.where(mask[..., None], (nbuf * 0.5 + 0.5) * 255.0, 128.0)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), mode="RGB")
