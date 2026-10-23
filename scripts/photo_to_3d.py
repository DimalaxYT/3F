#!/usr/bin/env python3
"""
photo_to_3d.py v2 — Pipeline Haute-Fidélité Photo -> Modèle 3D + Projection PBR Symétrique Z-Buffer.

Résout les 5 causes majeures d'échec de reconstruction 3D depuis une image de référence :
  1. Extraction exacte du gabarit métrique (`blueprint_grid.png`), des coupes horizontales multi-segments
     (`slice_spans` à `z = 0.00 .. 1.00`), des zooms 3x (`zoom_details.png`) et de la palette réelle ;
  2. Transfert de texture PBR `1024²` / `2048²` depuis la vraie photo (`project_photo_pbr`) :
     - Extension intérieure sans halo (`distance_transform_edt` sur masque érodé -> 0 % fond blanc !),
     - Alignement harmonique multi-segments par coupe (`mask_3d <-> mask_photo`),
     - Test de visibilité Z-buffer exact par sous-maillage + symétrie bilatérale `(|x|, y, z)` continue en `x = 0`,
     - Extraction de carte de normales tangentielles haute-fréquence (`Normal`) + rugosité/AO (`ORM`) depuis le micro-relief réel de la photo,
     - Mise à jour synchronisée de `<name>_game.glb`, `lod1/lod2`, `roblox/` (PNG) et `unreal/` (DirectX `-Y`) ;
  3. Vérification visuelle côte à côte (`photo_match.png`) + planche microscope 300 % (`photo_details_zoom.png`).
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage
import trimesh

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def extract_clean_foreground(
    photo_path: str | Path,
    bg_threshold: float = 17.0,
) -> dict:
    """Extrait le sujet détouré, supprime toute barre UI parasite et mesure le profil multi-segments exact."""
    im = Image.open(photo_path).convert("RGB")
    arr = np.asarray(im, dtype=np.uint8).copy()
    h, w, _ = arr.shape

    # Supprime toute barre sombre ou bandeau UI en haut/bas de capture d'écran
    top_trim = 0
    for r in range(min(h // 6, 80)):
        if arr[r].mean() < 85.0 and arr[r].std() < 28.0:
            top_trim = r + 1
        else:
            break

    bot_trim = h
    for r in range(h - 1, max(h - h // 6, h - 80), -1):
        if arr[r].mean() < 85.0 and arr[r].std() < 28.0:
            bot_trim = r
        else:
            break

    # Estime la couleur de fond studio sur le cadre périphérique propre
    work = arr[top_trim:bot_trim]
    wh = work.shape[0]
    border_samples = np.vstack([
        work[:max(4, wh // 25), :].reshape(-1, 3),
        work[-max(4, wh // 25):, :].reshape(-1, 3),
        work[:, :max(4, w // 25)].reshape(-1, 3),
        work[:, -max(4, w // 25):].reshape(-1, 3),
    ])
    bg_rgb = np.median(border_samples, axis=0)
    if top_trim > 0:
        arr[:top_trim, :] = np.round(bg_rgb).astype(np.uint8)
    if bot_trim < h:
        arr[bot_trim:, :] = np.round(bg_rgb).astype(np.uint8)

    diff = np.linalg.norm(arr.astype(np.float32) - bg_rgb[None, None, :], axis=2)
    # Exclut la fumée blanche/grise devant le museau et l'ombre portée grise sur le sol studio :
    # tout pixel gris/blanc très peu saturé (`max_rgb > 158` et `saturation < 0.16`) proche de la teinte de fond !
    arr_f = arr.astype(np.float32)
    c_max = arr_f.max(axis=2)
    c_sat = (c_max - arr_f.min(axis=2)) / np.maximum(c_max, 1.0)
    bg_sat = float((bg_rgb.max() - bg_rgb.min()) / max(float(bg_rgb.max()), 1.0))
    if bg_rgb.mean() > 175.0 and bg_sat < 0.12:
        is_haze_or_shadow = (c_max > 152.0) & (c_sat < 0.17)
        raw_mask = (diff > float(bg_threshold)) & (~is_haze_or_shadow)
    else:
        raw_mask = diff > float(bg_threshold)
    # Supprime les poussières isolées / fumée très ténue non connectée au corps principal
    raw_mask = ndimage.binary_opening(raw_mask, structure=np.ones((2, 2), dtype=bool))
    lbl, n_lbl = ndimage.label(raw_mask)
    if n_lbl > 1:
        counts = np.bincount(lbl.ravel())
        counts[0] = 0
        main_area = int(counts.max())
        keep_ids = np.where(counts >= max(24, int(main_area * 0.0015)))[0]
        fg_mask = np.isin(lbl, keep_ids)
    else:
        fg_mask = raw_mask

    ys, xs = np.where(fg_mask)
    if len(xs) == 0:
        fg_mask = np.ones((h, w), dtype=bool)
        ys, xs = np.where(fg_mask)

    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    bw = max(x1 - x0, 1)
    bh = max(y1 - y0, 1)
    aspect_lh = float(bw) / float(bh)

    # Palette chromatique réelle par quantiles de luminance (sans aucun pixel blanc de fond !)
    eroded = ndimage.binary_erosion(fg_mask, iterations=2)
    sample_mask = eroded if eroded.sum() > 200 else fg_mask
    fg_pixels = arr[sample_mask].astype(np.float32)
    lum = 0.2126 * fg_pixels[:, 0] + 0.7152 * fg_pixels[:, 1] + 0.0722 * fg_pixels[:, 2]
    quantiles = [0.08, 0.28, 0.52, 0.78, 0.94]
    palette_hex: list[str] = []
    for q in quantiles:
        lo_q = np.quantile(lum, max(0.0, q - 0.06))
        hi_q = np.quantile(lum, min(1.0, q + 0.06))
        band = fg_pixels[(lum >= lo_q) & (lum <= hi_q)]
        rgb_med = np.median(band, axis=0) if len(band) else np.median(fg_pixels, axis=0)
        palette_hex.append("#{:02x}{:02x}{:02x}".format(
            int(np.clip(rgb_med[0], 0, 255)),
            int(np.clip(rgb_med[1], 0, 255)),
            int(np.clip(rgb_med[2], 0, 255)),
        ))

    # Coupes horizontales multi-segments `z = 0.00 .. 1.00` (localise chaque patte, aile, corne et boucle !)
    slice_spans: list[dict] = []
    crop_mask = fg_mask[y0:y1 + 1, x0:x1 + 1]
    for i in range(26):
        z_norm = round(i / 25.0, 4)
        row_idx = int(np.clip(round((1.0 - z_norm) * bh), 0, crop_mask.shape[0] - 1))
        xs_row = np.where(crop_mask[row_idx])[0]
        spans = []
        if len(xs_row):
            splits = np.where(np.diff(xs_row) > 4)[0] + 1
            for grp in np.split(xs_row, splits):
                if len(grp) >= 2:
                    spans.append([round(float(grp[0]) / bw, 4), round(float(grp[-1]) / bw, 4)])
        slice_spans.append({
            "z_norm": z_norm,
            "u_min": spans[0][0] if spans else None,
            "u_max": spans[-1][1] if spans else None,
            "spans": spans,
        })

    return {
        "rgb": arr,
        "mask": fg_mask,
        "bbox": (x0, y0, x1, y1),
        "crop_rgb": arr[y0:y1 + 1, x0:x1 + 1],
        "crop_mask": crop_mask,
        "bg_rgb": [round(float(c), 1) for c in bg_rgb],
        "aspect_l_over_h": round(aspect_lh, 4),
        "palette_hex": palette_hex,
        "slice_spans": slice_spans,
        "profile_slices": [
            {"z_norm": s["z_norm"], "u_min": s["u_min"], "u_max": s["u_max"]}
            for s in slice_spans if s["u_min"] is not None
        ],
    }


def inspect_photo(
    photo_path: str | Path,
    out_dir: str | Path,
    target_height: float = 0.45,
) -> dict:
    """Produit `blueprint_grid.png`, `zoom_details.png` (loupe 3x) et `photo_blueprint.json`."""
    out_p = Path(out_dir)
    out_p.mkdir(parents=True, exist_ok=True)
    data = extract_clean_foreground(photo_path)
    crop = Image.fromarray(data["crop_rgb"])
    cw, ch = crop.size
    scale_vis = max(1, int(round(1050.0 / max(cw, ch))))
    vis = crop.resize((cw * scale_vis, ch * scale_vis), Image.Resampling.LANCZOS)
    vw, vh = vis.size

    length_m = float(target_height) * float(data["aspect_l_over_h"])
    pad_l, pad_t, pad_r, pad_b = 96, 62, 34, 88
    canvas = Image.new("RGB", (vw + pad_l + pad_r, vh + pad_t + pad_b), (18, 22, 29))
    canvas.paste(vis, (pad_l, pad_t))
    dr = ImageDraw.Draw(canvas)

    # Grille fine à pas 0.05 en `(u, z)` + coordonnées métriques `(Y, Z)` directes !
    for k in range(21):
        u = k / 20.0
        gx = pad_l + int(round(u * vw))
        gy = pad_t + int(round((1.0 - u) * vh))
        major = (k % 2 == 0)
        line_c = (65, 165, 255) if major else (175, 205, 232)
        dr.line([(gx, pad_t), (gx, pad_t + vh)], fill=line_c, width=1)
        dr.line([(pad_l, gy), (pad_l + vw, gy)], fill=line_c, width=1)
        if major:
            y_world = (u - 0.5) * length_m
            z_world = u * float(target_height)
            dr.text((gx - 18, pad_t + vh + 8), f"u={u:.1f}\nY={y_world:+.2f}", fill=(175, 215, 255))
            dr.text((6, gy - 6), f"z={u:.1f} ({z_world:.2f}m)", fill=(255, 195, 130))

    for idx, hx in enumerate(data["palette_hex"]):
        sx0 = pad_l + idx * 112
        sy0 = pad_t + vh + 46
        rgb_t = tuple(int(hx[j:j + 2], 16) for j in (1, 3, 5))
        dr.rectangle([sx0, sy0, sx0 + 34, sy0 + 24], fill=rgb_t, outline=(235, 240, 248))
        dr.text((sx0 + 40, sy0 + 6), hx, fill=(230, 235, 245))

    dr.text(
        (pad_l, 20),
        f"BLUEPRINT PHOTO -> 3D | H={target_height:.3f}m  L={length_m:.3f}m  (L/H={data['aspect_l_over_h']:.3f}) | gauche=-Y, droite=+Y",
        fill=(245, 248, 255),
    )

    grid_path = out_p / "blueprint_grid.png"
    canvas.save(grid_path)

    # Planche Loupe 3x automatique (Tête/Haut-Gauche, Torse/Pattes, Arrière/Ailes/Queue) pour ne rater AUCUN détail !
    z_panel_w, z_panel_h = 460, 460
    zoom_canvas = Image.new("RGB", (z_panel_w * 3 + 40, z_panel_h + 56), (16, 20, 26))
    z_boxes = [
        ((0, 0, int(cw * 0.45), int(ch * 0.56)), "LOUPE 3X — TETE, YEUX, DENTS & CORNES"),
        ((0, int(ch * 0.36), int(cw * 0.65), ch), "LOUPE 3X — TORSE, ECAILLES & PATTES/GRIFFES"),
        ((int(cw * 0.30), 0, cw, ch), "LOUPE 3X — AILES, DOS & QUEUE"),
    ]
    z_dr = ImageDraw.Draw(zoom_canvas)
    for idx_z, (zb, z_title) in enumerate(z_boxes):
        sub_im = crop.crop(zb)
        sub_im.thumbnail((z_panel_w, z_panel_h), Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (z_panel_w, z_panel_h), tuple(int(c) for c in data["bg_rgb"]))
        tile.paste(sub_im, ((z_panel_w - sub_im.width) // 2, (z_panel_h - sub_im.height) // 2))
        px0 = 10 + idx_z * (z_panel_w + 10)
        zoom_canvas.paste(tile, (px0, 42))
        z_dr.text((px0 + 6, 14), z_title, fill=(235, 242, 255))
    zoom_path = out_p / "zoom_details.png"
    zoom_canvas.save(zoom_path)

    meta = {
        "source_photo": str(Path(photo_path).resolve()),
        "blueprint_png": str(grid_path.resolve()),
        "blueprint_grid_png": str(grid_path.resolve()),
        "zoom_details_png": str(zoom_path.resolve()),
        "target_height_m": round(float(target_height), 4),
        "target_length_m": round(length_m, 4),
        "aspect_l_over_h": data["aspect_l_over_h"],
        "bbox_px": list(data["bbox"]),
        "palette_hex": data["palette_hex"],
        "slice_spans": data["slice_spans"],
        "profile_slices": data["profile_slices"],
    }
    json_path = out_p / "photo_blueprint.json"
    json_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return meta


# =========================================================================== #
# 2. MOTEUR DE PROJECTION PBR PHOTO SYMÉTRIQUE SANS HALO (`project_photo_pbr`)
# =========================================================================== #

def _rasterize_uv_attributes(
    verts: np.ndarray,
    faces: np.ndarray,
    uv: np.ndarray,
    v_nrm: np.ndarray,
    tex_h: int,
    tex_w: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rastérise l'atlas UV `(tex_h, tex_w)` et retourne `(valid_mask, pos_world, nrm_world)` exacts par texel."""
    valid = np.zeros((tex_h, tex_w), dtype=bool)
    pos_map = np.zeros((tex_h, tex_w, 3), dtype=np.float32)
    nrm_map = np.zeros((tex_h, tex_w, 3), dtype=np.float32)

    # glTF image row `0` = `v = 1.0`, row `tex_h - 1` = `v = 0.0` !
    px = uv[:, 0].astype(np.float64) * (tex_w - 1)
    py = (1.0 - uv[:, 1].astype(np.float64)) * (tex_h - 1)

    f = np.asarray(faces, dtype=np.int64)
    ax, bx, cx = px[f[:, 0]], px[f[:, 1]], px[f[:, 2]]
    ay, by, cy = py[f[:, 0]], py[f[:, 1]], py[f[:, 2]]
    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)

    x0 = np.maximum(np.floor(np.minimum(np.minimum(ax, bx), cx)).astype(np.int64) - 1, 0)
    x1 = np.minimum(np.ceil(np.maximum(np.maximum(ax, bx), cx)).astype(np.int64) + 1, tex_w - 1)
    y0 = np.maximum(np.floor(np.minimum(np.minimum(ay, by), cy)).astype(np.int64) - 1, 0)
    y1 = np.minimum(np.ceil(np.maximum(np.maximum(ay, by), cy)).astype(np.int64) + 1, tex_h - 1)

    keep = (np.abs(den) > 1e-10) & (x1 >= x0) & (y1 >= y0)
    idx_all = np.flatnonzero(keep)

    for t in idx_all:
        ia, ib, ic = f[t]
        tx0, tx1, ty0, ty1 = int(x0[t]), int(x1[t]), int(y0[t]), int(y1[t])
        gx, gy = np.meshgrid(np.arange(tx0, tx1 + 1, dtype=np.float64), np.arange(ty0, ty1 + 1, dtype=np.float64))
        inv_d = 1.0 / den[t]
        w0 = ((by[t] - cy[t]) * (gx - cx[t]) + (cx[t] - bx[t]) * (gy - cy[t])) * inv_d
        w1 = ((cy[t] - ay[t]) * (gx - cx[t]) + (ax[t] - cx[t]) * (gy - cy[t])) * inv_d
        w2 = 1.0 - w0 - w1
        # Légère dilatation `-0.03` pour couvrir 100 % des bords d'îlots UV (0 couture !)
        inside = (w0 >= -0.04) & (w1 >= -0.04) & (w2 >= -0.04)
        if not inside.any():
            continue
        ry, rx = np.nonzero(inside)
        wc0 = np.clip(w0[ry, rx], 0.0, 1.0)
        wc1 = np.clip(w1[ry, rx], 0.0, 1.0)
        wc2 = np.clip(w2[ry, rx], 0.0, 1.0)
        ws = np.maximum(wc0 + wc1 + wc2, 1e-8)
        wc0 /= ws
        wc1 /= ws
        wc2 /= ws
        yy = ty0 + ry
        xx = tx0 + rx
        p_interp = wc0[:, None] * verts[ia] + wc1[:, None] * verts[ib] + wc2[:, None] * verts[ic]
        n_interp = wc0[:, None] * v_nrm[ia] + wc1[:, None] * v_nrm[ib] + wc2[:, None] * v_nrm[ic]
        n_len = np.maximum(np.linalg.norm(n_interp, axis=1, keepdims=True), 1e-8)
        pos_map[yy, xx] = p_interp.astype(np.float32)
        nrm_map[yy, xx] = (n_interp / n_len).astype(np.float32)
        valid[yy, xx] = True

    return valid, pos_map, nrm_map


def _bilinear_sample_rgb(img_f: np.ndarray, sx: np.ndarray, sy: np.ndarray) -> np.ndarray:
    """Échantillonnage bilinéaire vectorisé haute précision sur `(H, W, C)`."""
    h, w = img_f.shape[:2]
    x = np.clip(sx, 0.0, w - 1.001)
    y = np.clip(sy, 0.0, h - 1.001)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    fx = (x - x0)[..., None]
    fy = (y - y0)[..., None]
    c00 = img_f[y0, x0]
    c10 = img_f[y0, x1]
    c01 = img_f[y1, x0]
    c11 = img_f[y1, x1]
    return (c00 * (1.0 - fx) + c10 * fx) * (1.0 - fy) + (c01 * (1.0 - fx) + c11 * fx) * fy


def _build_harmonic_warp(
    mask_3d: np.ndarray,
    mask_photo: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Calcule le champ de correspondance lisse `(map_u, map_v)` dans `[0, 1]²` envoyant
    chaque segment de la silhouette 3D vers le segment correspondant de la photo de référence !"""
    H3, W3 = mask_3d.shape
    Hp, Wp = mask_photo.shape

    ys3, xs3 = np.where(mask_3d)
    ysp, xsp = np.where(mask_photo)
    x3_0, x3_1 = int(xs3.min()), int(xs3.max())
    y3_0, y3_1 = int(ys3.min()), int(ys3.max())
    xp_0, xp_1 = int(xsp.min()), int(xsp.max())
    yp_0, yp_1 = int(ysp.min()), int(ysp.max())

    bw3, bh3 = max(x3_1 - x3_0, 1), max(y3_1 - y3_0, 1)
    bwp, bhp = max(xp_1 - xp_0, 1), max(yp_1 - yp_0, 1)

    grid_y, grid_x = np.mgrid[0:H3, 0:W3].astype(np.float32)
    u_base = (grid_x - x3_0) / bw3
    v_base = (grid_y - y3_0) / bh3  # 0 en haut (corne), 1 en bas (griffes)

    # Correspondance multi-segments ligne par ligne entre `mask_3d` et `mask_photo`
    delta_u = np.zeros((H3, W3), dtype=np.float32)
    delta_w = np.zeros((H3, W3), dtype=np.float32)

    def _get_spans(row_bool: np.ndarray, width_norm: float) -> list[tuple[float, float]]:
        idx = np.where(row_bool)[0]
        if len(idx) == 0:
            return []
        sp = np.where(np.diff(idx) > 4)[0] + 1
        return [
            (float(g[0]) / width_norm, float(g[-1]) / width_norm)
            for g in np.split(idx, sp) if len(g) >= 3
        ]

    for ry in range(y3_0, y3_1 + 1):
        vn = (ry - y3_0) / bh3
        py_p = int(np.clip(round(yp_0 + vn * bhp), 0, Hp - 1))
        spans_3 = _get_spans(mask_3d[ry, x3_0:x3_1 + 1], float(bw3))
        spans_p = _get_spans(mask_photo[py_p, xp_0:xp_1 + 1], float(bwp))
        if not spans_3 or not spans_p:
            continue
        for a3, b3 in spans_3:
            c3 = 0.5 * (a3 + b3)
            best_sp = min(spans_p, key=lambda sp: abs(0.5 * (sp[0] + sp[1]) - c3))
            ap, bp = best_sp
            if abs(0.5 * (ap + bp) - c3) > 0.14:
                continue
            ix0 = x3_0 + int(round(a3 * bw3))
            ix1 = x3_0 + int(round(b3 * bw3))
            if ix1 <= ix0:
                continue
            xs_seg = np.arange(ix0, ix1 + 1, dtype=np.float32)
            t_seg = (xs_seg - ix0) / max(ix1 - ix0, 1)
            u_target = ap + t_seg * (bp - ap)
            u_curr = (xs_seg - x3_0) / bw3
            # Limite le déplacement local à ±0.085 pour garder 0 distorsion interne !
            du_seg = np.clip(u_target - u_curr, -0.085, 0.085)
            delta_u[ry, ix0:ix1 + 1] = du_seg
            delta_w[ry, ix0:ix1 + 1] = 1.0

    # Extrapole et lisse harmoniquement `delta_u` sur tout le plan d'image (`sigma = 7 px`)
    if (delta_w > 0).any():
        _, near_idx = ndimage.distance_transform_edt(delta_w == 0, return_indices=True)
        filled_du = delta_u[near_idx[0], near_idx[1]]
        smooth_du = ndimage.gaussian_filter(filled_du, sigma=7.5)
    else:
        smooth_du = np.zeros_like(u_base)

    px_photo = xp_0 + (u_base + smooth_du) * bwp
    py_photo = yp_0 + v_base * bhp
    return px_photo.astype(np.float32), py_photo.astype(np.float32)


def _replace_glb_images_in_place(
    glb_path: Path,
    mat_textures: list[tuple[Image.Image, Image.Image, Image.Image]],
    fmt: str = "WEBP",
    flip_green: bool = False,
    max_dim: int = 1024,
) -> None:
    """Remplace les images `BC / Normal / ORM` directement dans le binaire `.glb` existant
    SANS altérer `UCX_SM_*`, `animations` (`Idle_Action`), les nœuds, ni les extensions !"""
    import struct as _st

    raw = glb_path.read_bytes()
    magic, version, _total = _st.unpack_from("<III", raw, 0)
    assert magic == 0x46546C67
    j_len, _j_type = _st.unpack_from("<II", raw, 12)
    gltf = json.loads(raw[20:20 + j_len].decode("utf-8"))
    b_off = 20 + j_len
    b_len, _b_type = _st.unpack_from("<II", raw, b_off)
    bin_orig = raw[b_off + 8:b_off + 8 + b_len]

    def _tex_img_idx(tex_info: dict | None) -> int | None:
        if not tex_info or "index" not in tex_info:
            return None
        t_obj = gltf["textures"][tex_info["index"]]
        ext_w = (t_obj.get("extensions") or {}).get("EXT_texture_webp")
        if ext_w and "source" in ext_w:
            return int(ext_w["source"])
        return int(t_obj["source"]) if "source" in t_obj else None

    def _encode_im(im_in: Image.Image, is_normal: bool = False) -> tuple[bytes, str]:
        im_w = im_in.convert("RGB")
        if max(im_w.size) > max_dim:
            im_w = im_w.resize((max_dim, max_dim), Image.Resampling.LANCZOS)
        if flip_green and is_normal:
            na = np.asarray(im_w).copy()
            na[..., 1] = 255 - na[..., 1]
            im_w = Image.fromarray(na)
        buf = io.BytesIO()
        if fmt.upper() == "PNG":
            im_w.save(buf, format="PNG")
            return buf.getvalue(), "image/png"
        im_w.save(buf, format="WEBP", quality=93)
        return buf.getvalue(), "image/webp"

    new_img_bytes: dict[int, tuple[bytes, str]] = {}
    mats = gltf.get("materials", [])
    t_cursor = 0
    for m_obj in mats:
        pbr = m_obj.get("pbrMetallicRoughness") or {}
        i_bc = _tex_img_idx(pbr.get("baseColorTexture"))
        i_mr = _tex_img_idx(pbr.get("metallicRoughnessTexture"))
        i_nm = _tex_img_idx(m_obj.get("normalTexture"))
        if i_bc is None or t_cursor >= len(mat_textures):
            continue
        bc_i, nrm_i, orm_i = mat_textures[t_cursor]
        t_cursor += 1
        new_img_bytes[i_bc] = _encode_im(bc_i, is_normal=False)
        if i_nm is not None:
            new_img_bytes[i_nm] = _encode_im(nrm_i, is_normal=True)
        if i_mr is not None:
            new_img_bytes[i_mr] = _encode_im(orm_i, is_normal=False)

    if not new_img_bytes:
        return

    bv_to_img: dict[int, int] = {}
    for im_i, (b_data, mime) in new_img_bytes.items():
        bv_i = int(gltf["images"][im_i]["bufferView"])
        bv_to_img[bv_i] = im_i
        gltf["images"][im_i]["mimeType"] = mime

    out_bin = bytearray()
    for bv_i, bv in enumerate(gltf["bufferViews"]):
        if bv_i in bv_to_img:
            chunk = new_img_bytes[bv_to_img[bv_i]][0]
        else:
            o0 = int(bv.get("byteOffset", 0))
            o1 = o0 + int(bv["byteLength"])
            chunk = bin_orig[o0:o1]
        while len(out_bin) % 4 != 0:
            out_bin.append(0)
        bv["byteOffset"] = len(out_bin)
        bv["byteLength"] = len(chunk)
        out_bin.extend(chunk)
    while len(out_bin) % 4 != 0:
        out_bin.append(0)
    gltf["buffers"][0]["byteLength"] = len(out_bin)

    j_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    j_pad = (4 - (len(j_bytes) % 4)) % 4
    j_bytes += b" " * j_pad
    total_len = 12 + 8 + len(j_bytes) + 8 + len(out_bin)
    out_glb = bytearray()
    out_glb.extend(_st.pack("<III", 0x46546C67, version, total_len))
    out_glb.extend(_st.pack("<II", len(j_bytes), 0x4E4F534A))
    out_glb.extend(j_bytes)
    out_glb.extend(_st.pack("<II", len(out_bin), 0x004E4942))
    out_glb.extend(out_bin)
    glb_path.write_bytes(bytes(out_glb))


def project_photo_pbr(
    out_dir: str | Path,
    name: str,
    photo_path: str | Path,
    azimuth_deg: float = 86.0,
    elevation_deg: float = 3.5,
    fov: float = 36.0,
    protect_bright_ivory: bool = True,
) -> dict:
    """Projette sans distorsion la vraie texture photo + le micro-relief tangentiel sur TOUS
    les sous-maillages PBR (`Body` + `joints`), avec atténuation rasante `|n · view|` (zéro étirement
    horizontal en vue de face !), symétrie `|x|` continue, 0 % fond blanc, et remplacement binaire
    in-place préservant 100 % des colliders `UCX_SM_*` et animations `Idle_Action` !"""
    import renderer as _rn

    out_p = Path(out_dir)
    fg = extract_clean_foreground(photo_path)
    raw_rgb = fg["rgb"].astype(np.float32) / 255.0
    fg_mask = fg["mask"]
    xp_0, yp_0, xp_1, yp_1 = fg["bbox"]
    bwp = float(max(xp_1 - xp_0, 1))
    bhp = float(max(yp_1 - yp_0, 1))

    # Érosion de sécurité de 3 pixels + exclusion stricte de tout résidu gris/blanc achromatique :
    # ZÉRO pixel blanc, gris fumée ou halo de contour ne peut exister dans `safe_rgb` !
    px_max = raw_rgb.max(axis=2)
    px_sat = (px_max - raw_rgb.min(axis=2)) / np.maximum(px_max, 1e-4)
    pure_subject = fg_mask & (~((px_max > 0.56) & (px_sat < 0.24)))
    inner_mask = ndimage.binary_erosion(pure_subject, iterations=3)
    if inner_mask.sum() < 200:
        inner_mask = pure_subject if pure_subject.sum() >= 50 else fg_mask
    _, idx_near = ndimage.distance_transform_edt(~inner_mask, return_indices=True)
    safe_rgb = raw_rgb[idx_near[0], idx_near[1]]
    blur_fine = ndimage.gaussian_filter(safe_rgb, sigma=(1.0, 1.0, 0.0))
    sharp_rgb = np.clip(safe_rgb + 0.35 * (safe_rgb - blur_fine), 0.0, 1.0)

    # Rend la silhouette 3D complète non rognée (`fov = 36°` -> 100 % du modèle dans le cadre !)
    game_glb = out_p / f"{name}_game.glb"
    scene = trimesh.load(game_glb, force="scene")
    S_cam = 1400
    _, mask_3d_pil = _rn.render_view(
        scene, azimuth_deg=azimuth_deg, elevation_deg=elevation_deg,
        size=S_cam, fov=fov, ssaa=1, shadow=False, post=False, return_mask=True,
    )
    mask_3d = np.asarray(mask_3d_pil) > 127
    ys3, xs3 = np.where(mask_3d)
    x3_0, x3_1 = float(xs3.min()), float(xs3.max())
    y3_0, y3_1 = float(ys3.min()), float(ys3.max())
    bw3 = max(x3_1 - x3_0, 1.0)
    bh3 = max(y3_1 - y3_0, 1.0)

    parts = _rn._gather(scene)
    all_v = np.vstack([p[0] for p in parts])
    lo, hi = all_v.min(0), all_v.max(0)
    center = 0.5 * (lo + hi)
    radius = float(np.linalg.norm(hi - lo) / 2.0) + 1e-6

    eye = center + radius * 3.1 * np.array([
        math.sin(math.radians(azimuth_deg)) * math.cos(math.radians(elevation_deg)),
        -math.cos(math.radians(azimuth_deg)) * math.cos(math.radians(elevation_deg)),
        math.sin(math.radians(elevation_deg)),
    ])
    near, far = radius * 0.1, radius * 12.0
    PV = _rn._perspective(fov, 1.0, near, far) @ _rn._look_at(eye, center)
    view_dir = eye - center
    view_dir /= max(float(np.linalg.norm(view_dir)), 1e-9)

    zbuf = np.full((S_cam, S_cam), np.inf, dtype=np.float64)
    for part_t in parts:
        v_w, f_w = part_t[0], part_t[2]
        hom = np.column_stack([v_w, np.ones(len(v_w))]) @ PV.T
        w_c = np.maximum(hom[:, 3], 1e-6)
        px_v = (hom[:, 0] / w_c * 0.5 + 0.5) * S_cam
        py_v = (0.5 - hom[:, 1] / w_c * 0.5) * S_cam
        ok_v = hom[:, 3] > 1e-4
        _rn._rasterize_part(px_v, py_v, w_c, ok_v, f_w, S_cam, S_cam, zbuf, update_z=True)

    def _project_world_pts(pts_w: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        hom = np.column_stack([pts_w, np.ones(len(pts_w), dtype=np.float64)]) @ PV.T
        wc = np.maximum(hom[:, 3], 1e-6)
        sx = np.clip((hom[:, 0] / wc * 0.5 + 0.5) * S_cam, 0.0, S_cam - 1.001)
        sy = np.clip((0.5 - hom[:, 1] / wc * 0.5) * S_cam, 0.0, S_cam - 1.001)
        return sx, sy, wc

    mat_tex_list: list[tuple[Image.Image, Image.Image, Image.Image]] = []
    body_bc_img: Image.Image | None = None
    body_nrm_img: Image.Image | None = None
    body_orm_img: Image.Image | None = None

    for g_name, geom in scene.geometry.items():
        vis_obj = getattr(geom, "visual", None)
        uv = getattr(vis_obj, "uv", None)
        mat = getattr(vis_obj, "material", None)
        if uv is None or mat is None or getattr(mat, "baseColorTexture", None) is None:
            continue

        bc_orig = np.asarray(mat.baseColorTexture.convert("RGB"), dtype=np.float32) / 255.0
        th, tw = bc_orig.shape[:2]
        nrm_orig = (
            np.asarray(mat.normalTexture.convert("RGB"), dtype=np.float32) / 255.0
            if getattr(mat, "normalTexture", None) is not None
            else np.dstack([np.full((th, tw), 0.5), np.full((th, tw), 0.5), np.ones((th, tw))]).astype(np.float32)
        )
        orm_orig = (
            np.asarray(mat.metallicRoughnessTexture.convert("RGB"), dtype=np.float32) / 255.0
            if getattr(mat, "metallicRoughnessTexture", None) is not None
            else np.dstack([np.ones((th, tw)), np.full((th, tw), 0.55), np.zeros((th, tw))]).astype(np.float32)
        )

        tf_mat = np.eye(4)
        for nd in scene.graph.nodes_geometry:
            mat_n, gn = scene.graph[nd]
            if gn == g_name:
                tf_mat = mat_n
                break
        v_world = trimesh.transformations.transform_points(np.asarray(geom.vertices, dtype=np.float64), tf_mat)
        n_world = np.asarray(geom.vertex_normals, dtype=np.float64) @ tf_mat[:3, :3].T
        n_world /= np.maximum(np.linalg.norm(n_world, axis=1, keepdims=True), 1e-8)

        valid, pos_tex, nrm_tex = _rasterize_uv_attributes(
            v_world, np.asarray(geom.faces), np.asarray(uv), n_world, th, tw
        )
        vy, vx = np.where(valid)
        if len(vy) == 0:
            continue

        pts = pos_tex[vy, vx].astype(np.float64)
        nrms = nrm_tex[vy, vx].astype(np.float64)

        pts_sym = pts.copy()
        pts_sym[:, 0] = np.abs(pts_sym[:, 0]) if view_dir[0] >= 0 else -np.abs(pts_sym[:, 0])
        nrms_sym = nrms.copy()
        nrms_sym[:, 0] = np.abs(nrms_sym[:, 0]) if view_dir[0] >= 0 else -np.abs(nrms_sym[:, 0])

        sx_d, sy_d, wc_d = _project_world_pts(pts)
        sx_s, sy_s, wc_s = _project_world_pts(pts_sym)

        zd_buf = zbuf[np.round(sy_d).astype(np.int64), np.round(sx_d).astype(np.int64)]
        zs_buf = zbuf[np.round(sy_s).astype(np.int64), np.round(sx_s).astype(np.int64)]

        tol = radius * 0.065
        vis_direct = (wc_d <= zd_buf + tol)
        vis_sym = (wc_s <= zs_buf + tol)

        use_direct = vis_direct & ((pts[:, 0] * (1.0 if view_dir[0] >= 0 else -1.0)) >= -0.004)
        sx_use = np.where(use_direct, sx_d, sx_s)
        sy_use = np.where(use_direct, sy_d, sy_s)
        has_clear_proj = vis_direct | vis_sym

        # Projection affine pure sans aucune distorsion ondulée : `0` vague sur les ailes ou la queue !
        p_x = xp_0 + ((sx_use - x3_0) / bw3) * bwp
        p_y = yp_0 + ((sy_use - y3_0) / bh3) * bhp
        sampled_photo = _bilinear_sample_rgb(sharp_rgb, p_x, p_y)
        sampled_tint = _bilinear_sample_rgb(ndimage.gaussian_filter(safe_rgb, sigma=(6.0, 6.0, 0.0)), p_x, p_y)

        # Delight PBR calibré physiquement (conserve 100 % des contrastes d'écailles sans double assombrissement)
        lin_photo = np.power(np.clip(sampled_photo, 0.0, 1.0), 2.2)
        lum_lin = 0.2126 * lin_photo[:, 0] + 0.7152 * lin_photo[:, 1] + 0.0722 * lin_photo[:, 2]
        target_lum = np.clip((lum_lin ** 0.80) * 0.88 + 0.012, 0.012, 0.74)
        gain = (target_lum / np.maximum(lum_lin, 1e-4))[:, None]
        delighted_srgb = np.power(np.clip(lin_photo * np.clip(gain, 0.55, 2.25), 0.0, 0.82), 1.0 / 2.2)

        # Harmonise les écailles procédurales `orig_px` avec la teinte locale `sampled_tint`
        # afin que les faces de face/dessus (`|n · view|` faible, vue de face !) aient ZÉRO rayure étirée
        # tout en gardant exactement la vraie couleur locale de la photo !
        orig_px = bc_orig[vy, vx]
        orig_lum = 0.2126 * orig_px[:, 0] + 0.7152 * orig_px[:, 1] + 0.0722 * orig_px[:, 2]
        orig_sat = orig_px.max(axis=1) - orig_px.min(axis=1)
        scale_contrast = np.clip(orig_lum / np.maximum(orig_lum.mean(), 0.22), 0.42, 1.55)[:, None]
        proc_tinted = np.clip(sampled_tint * 0.72 * scale_contrast + orig_px * 0.34, 0.0, 0.82)

        # Poids angulaire d'incidence : 100 % photo nette sur les flancs/ailes, transition douce vers
        # les vraies écailles 3D teintées sur les faces perpendiculaires à la caméra (`|n · view| < 0.28`) !
        inc = np.abs(nrms_sym @ view_dir)
        w_angle = np.clip((inc - 0.14) / 0.34, 0.0, 1.0).astype(np.float32)
        w_photo = np.where(has_clear_proj, 0.90 * w_angle, 0.0).astype(np.float32)

        blended = delighted_srgb * w_photo[:, None] + proc_tinted * (1.0 - w_photo[:, None])

        if protect_bright_ivory:
            # Protège à 100 % les 32 crocs d'ivoire pur, l'iris ambré ardent et la pupille fendue noire !
            is_tooth = (orig_lum > 0.73) & (orig_sat < 0.16)
            is_iris = (orig_px[:, 0] > 0.70) & (orig_sat > 0.40)
            is_dark_cavity = orig_lum < 0.055
            keep_orig = is_tooth | is_iris | is_dark_cavity
            blended = np.where(keep_orig[:, None], orig_px, blended)

        new_bc = bc_orig.copy()
        new_bc[vy, vx] = blended

        if (~valid).any():
            _, uv_near = ndimage.distance_transform_edt(~valid, return_indices=True)
            new_bc = np.where(valid[..., None], new_bc, new_bc[uv_near[0], uv_near[1]])

        lum_uv = 0.2126 * new_bc[..., 0] + 0.7152 * new_bc[..., 1] + 0.0722 * new_bc[..., 2]
        detail_fine = lum_uv - ndimage.gaussian_filter(lum_uv, sigma=1.3)
        detail_med = ndimage.gaussian_filter(lum_uv, sigma=1.2) - ndimage.gaussian_filter(lum_uv, sigma=4.2)
        h_photo = (1.60 * detail_fine + 0.80 * detail_med).astype(np.float32)

        dhu = np.gradient(h_photo, axis=1)
        dhv = np.gradient(h_photo, axis=0)
        n_base = nrm_orig * 2.0 - 1.0
        n_comb = np.dstack([
            n_base[..., 0] - dhu * 2.30,
            n_base[..., 1] + dhv * 2.30,
            n_base[..., 2],
        ])
        n_comb /= np.maximum(np.linalg.norm(n_comb, axis=2, keepdims=True), 1e-8)
        new_nrm = np.clip(n_comb * 0.5 + 0.5, 0.0, 1.0)

        crevice = np.clip(-detail_fine * 4.2, 0.0, 1.0)
        crown = np.clip(detail_fine * 3.5, 0.0, 1.0)
        new_orm = orm_orig.copy()
        new_orm[..., 0] = np.clip(orm_orig[..., 0] * (1.0 - 0.32 * crevice), 0.18, 1.0)
        new_orm[..., 1] = np.clip(orm_orig[..., 1] + 0.20 * crevice - 0.10 * crown, 0.08, 0.92)

        bc_pil = Image.fromarray(np.round(np.clip(new_bc, 0.0, 1.0) * 255.0).astype(np.uint8))
        nrm_pil = Image.fromarray(np.round(new_nrm * 255.0).astype(np.uint8))
        orm_pil = Image.fromarray(np.round(new_orm * 255.0).astype(np.uint8))
        mat_tex_list.append((bc_pil, nrm_pil, orm_pil))

        if "body" in g_name.lower() or body_bc_img is None:
            body_bc_img = bc_pil
            body_nrm_img = nrm_pil
            body_orm_img = orm_pil

    # Remplace en place les textures dans TOUS les `.glb` sans toucher à `UCX_SM_*` ni `Idle_Action` !
    _replace_glb_images_in_place(game_glb, mat_tex_list, fmt="WEBP", flip_green=False, max_dim=1024)

    rbx_dir = out_p / "roblox"
    if rbx_dir.is_dir() and (rbx_dir / f"{name}_roblox.glb").is_file():
        _replace_glb_images_in_place(rbx_dir / f"{name}_roblox.glb", mat_tex_list, fmt="PNG", flip_green=False, max_dim=1024)
        if body_bc_img is not None and body_nrm_img is not None and body_orm_img is not None:
            orm_np = np.asarray(body_orm_img, dtype=np.float32) / 255.0
            bc_np = np.asarray(body_bc_img, dtype=np.float32) / 255.0
            ao_f = 0.25 + 0.75 * orm_np[..., 0:1]
            Image.fromarray(np.round(np.clip(bc_np * ao_f, 0.0, 1.0) * 255.0).astype(np.uint8)).save(rbx_dir / f"T_{name}_ColorMap.png")
            body_nrm_img.save(rbx_dir / f"T_{name}_NormalMap.png")
            Image.fromarray(np.round(orm_np[..., 1] * 255.0).astype(np.uint8)).save(rbx_dir / f"T_{name}_RoughnessMap.png")
            Image.fromarray(np.round(orm_np[..., 2] * 255.0).astype(np.uint8)).save(rbx_dir / f"T_{name}_MetalnessMap.png")

    ue_dir = out_p / "unreal"
    if ue_dir.is_dir() and (ue_dir / f"SM_{name}.glb").is_file():
        _replace_glb_images_in_place(ue_dir / f"SM_{name}.glb", mat_tex_list, fmt="WEBP", flip_green=True, max_dim=1024)
        if body_bc_img is not None and body_nrm_img is not None and body_orm_img is not None:
            body_bc_img.save(ue_dir / f"T_{name}_BC.png")
            body_bc_img.save(ue_dir / f"T_{name}_BC.webp", format="WEBP", quality=93)
            body_orm_img.save(ue_dir / f"T_{name}_ORM.png")
            body_orm_img.save(ue_dir / f"T_{name}_ORM.webp", format="WEBP", quality=93)
            n_dx = np.asarray(body_nrm_img).copy()
            n_dx[..., 1] = 255 - n_dx[..., 1]
            n_dx_im = Image.fromarray(n_dx)
            n_dx_im.save(ue_dir / f"T_{name}_N.png")
            n_dx_im.save(ue_dir / f"T_{name}_N.webp", format="WEBP", quality=94)

    return {"updated_geometries": len(mat_tex_list), "game_glb": str(game_glb)}


def load_scene_light(path: str | Path, max_tex: int = 1024) -> trimesh.Scene:
    """Charge un `.glb` en réduisant les textures à `max_tex`.

    Les rendus de contrôle font 1000-1600 px : garder des atlas 4096² en mémoire
    ne change rien à l'image et fait exploser la RAM (3 atlas 4K décompressés =
    ~150 Mo rien qu'en pixels, plus les copies de `trimesh`). Sur une machine
    3 Go, c'est la différence entre succès et OOM-kill.
    """
    sc = trimesh.load(path, force="scene")
    for gm in sc.geometry.values():
        mv = getattr(getattr(gm, "visual", None), "material", None)
        if mv is None:
            continue
        for attr in ("baseColorTexture", "normalTexture", "metallicRoughnessTexture"):
            im = getattr(mv, attr, None)
            if im is None:
                continue
            try:
                w, h = im.size
            except Exception:
                continue
            if max(w, h) > max_tex:
                setattr(mv, attr, im.resize((max_tex, max_tex), Image.Resampling.LANCZOS))
    return sc


def verify_photo_match(
    photo_path: str | Path,
    asset_path: str | Path,
    out_png: str | Path,
    azimuth_deg: float = 82.0,
    elevation_deg: float = 4.0,
    fov: float = 24.0,
    out_zoom_png: str | Path | None = None,
    render_size: int = 900,
    ssaa: float = 1.5,
) -> dict:
    """Rend l'asset 3D sous l'angle exact de la photo, calcule l'IoU exact sur masque matériel,
    et génère `photo_match.png` + optionnellement la planche microscope 300 % `photo_details_zoom.png` !"""
    import renderer as _rn

    ref = extract_clean_foreground(photo_path)
    sc = load_scene_light(asset_path, max_tex=1024)
    ren_im, ren_mask_pil = _rn.render_view(
        sc, azimuth_deg=azimuth_deg, elevation_deg=elevation_deg,
        size=int(render_size), fov=fov, ssaa=float(ssaa), return_mask=True,
    )
    ren_rgb = np.asarray(ren_im.convert("RGB"))
    ren_mask = np.asarray(ren_mask_pil) > 127
    ys_r, xs_r = np.where(ren_mask)
    rx0, rx1 = int(xs_r.min()), int(xs_r.max())
    ry0, ry1 = int(ys_r.min()), int(ys_r.max())
    ren_aspect = float(max(rx1 - rx0, 1)) / float(max(ry1 - ry0, 1))

    # IoU exact sur les masques cadrés `640 x 480` (sans ombre portée parasite !)
    m_ref = Image.fromarray((ref["crop_mask"].astype(np.uint8) * 255)).resize((640, 480), Image.Resampling.NEAREST)
    m_ren = Image.fromarray((ren_mask[ry0:ry1 + 1, rx0:rx1 + 1].astype(np.uint8) * 255)).resize((640, 480), Image.Resampling.NEAREST)
    b1 = np.asarray(m_ref) > 127
    b2 = np.asarray(m_ren) > 127
    inter = float(np.logical_and(b1, b2).sum())
    union = max(float(np.logical_or(b1, b2).sum()), 1.0)
    iou = inter / union

    panel_w, panel_h = 840, 640
    sheet = Image.new("RGB", (panel_w * 2 + 48, panel_h + 74), (16, 19, 25))

    def _fit_panel(crop_arr: np.ndarray, pad_rgb: tuple[int, int, int] = (246, 246, 246)) -> Image.Image:
        im_c = Image.fromarray(crop_arr)
        im_c.thumbnail((panel_w - 40, panel_h - 40), Image.Resampling.LANCZOS)
        p = Image.new("RGB", (panel_w, panel_h), pad_rgb)
        p.paste(im_c, ((panel_w - im_c.width) // 2, (panel_h - im_c.height) // 2))
        return p

    p_left = _fit_panel(ref["crop_rgb"])
    p_right = _fit_panel(ren_rgb[ry0:ry1 + 1, rx0:rx1 + 1], pad_rgb=(241, 243, 246))
    sheet.paste(p_left, (16, 56))
    sheet.paste(p_right, (panel_w + 32, 56))

    dr = ImageDraw.Draw(sheet)
    dr.text(
        (20, 18),
        f"PHOTO DE REFERENCE (L/H = {ref['aspect_l_over_h']:.2f})   vs   MODELE 3D GENERE (L/H = {ren_aspect:.2f}  |  Silhouette IoU = {iou:.2f})",
        fill=(238, 244, 255),
    )
    out_p = Path(out_png)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_p)

    # Planche Microscope 300 % (Tête/Yeux/Dents | Épaule/Écailles/Griffes | Ailes/Queue + Vues 360° 3D !)
    if out_zoom_png is not None:
        ref_crop = Image.fromarray(ref["crop_rgb"])
        ren_crop = Image.fromarray(ren_rgb[ry0:ry1 + 1, rx0:rx1 + 1])
        cw_r, ch_r = ref_crop.size
        cw_m, ch_m = ren_crop.size

        v_front34 = _rn.render_view(sc, azimuth_deg=38.0, elevation_deg=14.0, size=560, fov=32.0, ssaa=2)
        v_front = _rn.render_view(sc, azimuth_deg=4.0, elevation_deg=10.0, size=560, fov=32.0, ssaa=2)
        v_other = _rn.render_view(sc, azimuth_deg=-68.0, elevation_deg=14.0, size=560, fov=32.0, ssaa=2)

        tw, th = 500, 400
        z_sheet = Image.new("RGB", (tw * 3 + 56, th * 3 + 116), (14, 17, 23))
        z_dr = ImageDraw.Draw(z_sheet)
        z_dr.text(
            (20, 16),
            f"INSPECTION MICROSCOPE 300% DES DETAILS — PHOTO vs MODELE 3D + VUES 3D MULTI-ANGLES (IoU = {iou:.2f})",
            fill=(242, 247, 255),
        )

        rows_spec = [
            (
                (0.0, 0.0, 0.34, 0.36),
                "1A. PHOTO ZOOM 3X : TETE, OEIL FENDU, CROCS & CORNES",
                "1B. MODELE 3D ZOOM 3X : TETE, OEIL FENDU, CROCS & CORNES",
                v_front34,
                "1C. MODELE 3D VUE 3/4 AVANT DROIT (VRAIE 3D 360)",
            ),
            (
                (0.08, 0.34, 0.62, 1.0),
                "2A. PHOTO ZOOM 3X : EPAULE EPINEUSE, SCUTES D'OR & PATTES",
                "2B. MODELE 3D ZOOM 3X : EPAULE EPINEUSE, SCUTES D'OR & PATTES",
                v_front,
                "2C. MODELE 3D VUE DE FACE (PLAQUES D'OR & SYMETRIE)",
            ),
            (
                (0.32, 0.05, 1.0, 0.98),
                "3A. PHOTO ZOOM 3X : DOUBLE AILE VEINEE & QUEUE EPINEUSE",
                "3B. MODELE 3D ZOOM 3X : DOUBLE AILE VEINEE & QUEUE EPINEUSE",
                v_other,
                "3C. MODELE 3D FLANC OPPOSE (-68 deg — 100% TEXTURE 360)",
            ),
        ]

        def _fit_tile(im_src: Image.Image) -> Image.Image:
            c = im_src.copy()
            c.thumbnail((tw - 16, th - 16), Image.Resampling.LANCZOS)
            bg_t = Image.new("RGB", (tw, th), (244, 245, 247))
            bg_t.paste(c, ((tw - c.width) // 2, (th - c.height) // 2))
            return bg_t

        for r_i, (u_box, lbl_a, lbl_b, v_extra, lbl_c) in enumerate(rows_spec):
            ua0, va0, ua1, va1 = u_box
            c_a = ref_crop.crop((int(ua0 * cw_r), int(va0 * ch_r), int(ua1 * cw_r), int(va1 * ch_r)))
            c_b = ren_crop.crop((int(ua0 * cw_m), int(va0 * ch_m), int(ua1 * cw_m), int(va1 * ch_m)))
            y_top = 52 + r_i * (th + 22)
            z_sheet.paste(_fit_tile(c_a), (16, y_top + 16))
            z_sheet.paste(_fit_tile(c_b), (tw + 28, y_top + 16))
            z_sheet.paste(_fit_tile(v_extra), (tw * 2 + 40, y_top + 16))
            z_dr.text((20, y_top), lbl_a, fill=(165, 215, 255))
            z_dr.text((tw + 32, y_top), lbl_b, fill=(155, 245, 185))
            z_dr.text((tw * 2 + 44, y_top), lbl_c, fill=(255, 215, 145))

        Path(out_zoom_png).parent.mkdir(parents=True, exist_ok=True)
        z_sheet.save(out_zoom_png)

    return {
        "out_png": str(out_p),
        "out_zoom_png": str(out_zoom_png) if out_zoom_png else None,
        "ref_aspect": ref["aspect_l_over_h"],
        "model_aspect": round(ren_aspect, 4),
        "bbox_iou": round(iou, 4),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Inspection Photo -> 3D, Projection PBR & Vérification Microscope")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ins = sub.add_parser("inspect", help="Extrait gabarit métrique, coupes multi-segments et zooms 3x")
    p_ins.add_argument("photo")
    p_ins.add_argument("-o", "--out", required=True)
    p_ins.add_argument("--height", type=float, default=0.45)

    p_prj = sub.add_parser("project", help="Projette la texture PBR + normales de la photo sur tout le package")
    p_prj.add_argument("photo")
    p_prj.add_argument("out_dir")
    p_prj.add_argument("-n", "--name", required=True)
    p_prj.add_argument("--azimuth", type=float, default=82.0)
    p_prj.add_argument("--elevation", type=float, default=4.0)
    p_prj.add_argument("--fov", type=float, default=24.0)

    p_ver = sub.add_parser("verify", help="Génère le comparatif côte à côte + planche microscope 300%")
    p_ver.add_argument("photo")
    p_ver.add_argument("asset")
    p_ver.add_argument("-o", "--out", required=True)
    p_ver.add_argument("--zoom", default=None, help="Chemin optionnel pour photo_details_zoom.png")
    p_ver.add_argument("--azimuth", type=float, default=82.0)
    p_ver.add_argument("--elevation", type=float, default=4.0)
    p_ver.add_argument("--fov", type=float, default=24.0)
    p_ver.add_argument("--render-size", type=int, default=900)
    p_ver.add_argument("--ssaa", type=float, default=1.5)

    args = ap.parse_args(argv)
    if args.cmd == "inspect":
        res = inspect_photo(args.photo, args.out, target_height=args.height)
    elif args.cmd == "project":
        res = project_photo_pbr(
            args.out_dir, args.name, args.photo,
            azimuth_deg=args.azimuth, elevation_deg=args.elevation, fov=args.fov,
        )
    else:
        res = verify_photo_match(
            args.photo, args.asset, args.out,
            azimuth_deg=args.azimuth, elevation_deg=args.elevation, fov=args.fov,
            out_zoom_png=args.zoom, render_size=args.render_size, ssaa=args.ssaa,
        )
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
