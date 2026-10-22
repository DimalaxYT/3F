#!/usr/bin/env python3
"""
photo_to_3d.py — Pipeline fidèle « Photo Réelle -> Modèle 3D » pour 3d-forge.

Résout les 3 causes majeures d'échec des agents IA quand un utilisateur envoie une photo
et demande « génère-moi ça à partir de la photo » :
  1. Fini l'invention à l'aveugle ou la copie d'une recette générique du catalogue :
     `inspect` détoure proprement le sujet (sans l'ombre portée au sol), mesure son ratio
     exact `L / H`, extrait la vraie palette hexadécimale `#RRGGBB` des pixels internes,
     imprime une carte silhouette métrique `(y, z)` prête à coder, et génère `blueprint_grid.png`
     (photo quadrillée graduée de `0.00` à `1.00` que l'agent lit avec `read_file`).
  2. `project_photo_albedo` projette directement les nuances chromatiques de la photo
     (érodées à l'intérieur du masque pour zéro bavure blanche du fond !) sur le High-Poly 3D.
  3. `verify` rend le modèle 3D généré sous le même angle caméra que la photo et assemble
     `photo_match.png` (`[Photo demandée | Modèle 3D généré + métriques]`) pour contrôle visuel
     obligatoire avant livraison du `.zip` !

Commandes CLI :
  python3 scripts/photo_to_3d.py inspect <photo.png> -o out/ref_analysis [--height 0.42]
  python3 scripts/photo_to_3d.py verify  <photo.png> <asset.glb> -o out/photo_match.png [--az -62 --el 8]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def extract_subject_mask_and_crop(img_path: str | Path) -> dict:
    """Détoure automatiquement un sujet photographié sur fond clair, sombre ou alpha,
    en éliminant les barres UI éventuelles et les ombres douces projetées au sol."""
    im = Image.open(img_path).convert("RGBA")
    rgba = np.asarray(im, dtype=np.float32) / 255.0
    rgb = rgba[..., :3]
    alpha = rgba[..., 3]
    h0, w0, _ = rgb.shape

    # Supprime une éventuelle barre de capture d'écran sombre/unie tout en haut
    row_lum = rgb.mean(axis=(1, 2))
    top_cut = 0
    if float(alpha.mean()) > 0.95:
        border_med = float(np.median(row_lum[max(h0 // 6, 1):]))
        while top_cut < h0 // 5 and abs(float(row_lum[top_cut]) - border_med) > 0.35:
            top_cut += 1
    rgb = rgb[top_cut:]
    alpha = alpha[top_cut:]
    h, w, _ = rgb.shape

    border_a = np.concatenate([alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]])
    if float(border_a.mean()) < 0.5:
        fg = alpha > 0.45
    else:
        border_rgb = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]], axis=0)
        bg_med = np.median(border_rgb, axis=0)
        bg_lum = float(bg_med.mean())
        cmax = rgb.max(axis=2)
        cmin = rgb.min(axis=2)
        sat = np.where(cmax > 1e-4, (cmax - cmin) / np.maximum(cmax, 1e-4), 0.0)
        diff = np.linalg.norm(rgb - bg_med[None, None, :], axis=2)
        if bg_lum > 0.65:
            # Fond clair studio : rejette l'ombre grise au sol (faible saturation + luminance moyenne/haute)
            fg = (sat > 0.13) | (cmax < bg_lum - 0.24)
        else:
            fg = diff > 0.16

    fg = ndimage.binary_opening(fg, np.ones((3, 3), dtype=bool))
    fg = ndimage.binary_closing(fg, np.ones((5, 5), dtype=bool))
    lbl, n_comp = ndimage.label(fg)
    if n_comp > 1:
        sizes = ndimage.sum(fg, lbl, range(1, n_comp + 1))
        max_sz = float(np.max(sizes))
        keep_ids = [i + 1 for i, sz in enumerate(sizes) if sz >= 0.015 * max_sz]
        fg = np.isin(lbl, keep_ids)

    ys, xs = np.where(fg)
    if len(xs) < 16:
        x0, y0, x1, y1 = 0, 0, w - 1, h - 1
        fg = np.ones((h, w), dtype=bool)
    else:
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())

    crop_rgb = rgb[y0:y1 + 1, x0:x1 + 1]
    crop_mask = fg[y0:y1 + 1, x0:x1 + 1]
    return {
        "crop_rgb": crop_rgb,
        "crop_mask": crop_mask,
        "bbox_px": [x0, y0 + top_cut, x1, y1 + top_cut],
        "aspect_l_over_h": float((x1 - x0 + 1) / max(y1 - y0 + 1, 1)),
    }


def inspect_photo(photo_path: str | Path, out_dir: str | Path, target_height: float = 0.40) -> dict:
    """Génère `blueprint_grid.png` + `photo_blueprint.json` + carte ASCII métrique `(y, z)`."""
    out_p = Path(out_dir)
    out_p.mkdir(parents=True, exist_ok=True)
    data = extract_subject_mask_and_crop(photo_path)
    crop_rgb = data["crop_rgb"]
    mask = data["crop_mask"]
    ratio = data["aspect_l_over_h"]
    H_m = float(target_height)
    L_m = H_m * ratio

    # Érosion stricte pour n'échantillonner AUCUN pixel de contour mêlé au fond
    inner = ndimage.binary_erosion(mask, iterations=3)
    pts_rgb = crop_rgb[inner] if inner.sum() >= 32 else crop_rgb[mask]
    hex_stops = {}
    for q, tag in ((10, "crevice_dark"), (28, "primary_dark"), (50, "primary_mid"), (75, "secondary_warm"), (90, "highlight_accent")):
        c = np.percentile(pts_rgb, q, axis=0)
        hex_stops[tag] = "#%02x%02x%02x" % tuple(int(np.clip(v * 255.0, 0, 255)) for v in c)

    # Planche quadrillée haute lisibilité pour `read_file`
    bh, bw, _ = crop_rgb.shape
    scale = 760.0 / max(bw, bh)
    gw, gh = max(int(round(bw * scale)), 120), max(int(round(bh * scale)), 120)
    pad_l, pad_t, pad_r, pad_b = 74, 52, 260, 56
    canvas = Image.new("RGB", (pad_l + gw + pad_r, pad_t + gh + pad_b), (18, 22, 30))

    vis_np = crop_rgb.copy()
    vis_np[~mask] = vis_np[~mask] * 0.22 + np.array([0.09, 0.11, 0.15], dtype=np.float32) * 0.78
    vis_im = Image.fromarray((np.clip(vis_np, 0.0, 1.0) * 255).astype(np.uint8)).resize((gw, gh), Image.Resampling.LANCZOS)
    canvas.paste(vis_im, (pad_l, pad_t))
    dr = ImageDraw.Draw(canvas)

    dr.text((pad_l, 16), f"BLUEPRINT PHOTO -> 3D  |  H = {H_m:.3f} m  |  L = {L_m:.3f} m  (L/H = {ratio:.3f})", fill=(235, 242, 255))
    for i in range(11):
        u = i / 10.0
        px = pad_l + int(round(u * gw))
        y_m = (u - 0.5) * L_m
        col_g = (95, 130, 195) if i in (0, 5, 10) else (58, 72, 98)
        dr.line([(px, pad_t), (px, pad_t + gh)], fill=col_g, width=2 if i == 5 else 1)
        dr.text((px - 18, pad_t + gh + 8), f"{y_m:+.2f}m", fill=(185, 200, 228))

        py = pad_t + int(round((1.0 - u) * gh))
        z_m = u * H_m
        dr.line([(pad_l, py), (pad_l + gw, py)], fill=col_g, width=2 if i == 0 else 1)
        dr.text((8, py - 6), f"z={z_m:.2f}", fill=(185, 200, 228))

    # Pastilles de vraies couleurs mesurées sur la photo
    sx0 = pad_l + gw + 18
    dr.text((sx0, pad_t), "PALETTE MESUREE (ZERO INVENTION)", fill=(235, 242, 255))
    for idx, (k_tag, hex_v) in enumerate(hex_stops.items()):
        yy = pad_t + 28 + idx * 42
        rgb_t = tuple(int(hex_v[j:j + 2], 16) for j in (1, 3, 5))
        dr.rectangle([sx0, yy, sx0 + 36, yy + 28], fill=rgb_t, outline=(220, 226, 240))
        dr.text((sx0 + 46, yy + 7), f"{k_tag}: {hex_v}", fill=(215, 224, 242))

    bp_path = out_p / "blueprint_grid.png"
    canvas.save(bp_path)

    # Carte silhouette ASCII en coordonnées métriques réelles
    ascii_rows = []
    ny, nx = 22, 52
    for j in range(ny):
        z_val = H_m * (1.0 - (j + 0.5) / ny)
        r0, r1 = int(j * bh / ny), max(int((j + 1) * bh / ny), int(j * bh / ny) + 1)
        row_chars = [
            "#" if mask[r0:r1, int(i * bw / nx):max(int((i + 1) * bw / nx), int(i * bw / nx) + 1)].mean() > 0.18 else "."
            for i in range(nx)
        ]
        ascii_rows.append(f"z={z_val:0.3f}m | {''.join(row_chars)}")

    summary = {
        "photo": str(photo_path),
        "blueprint_png": str(bp_path),
        "height_m": round(H_m, 4),
        "length_m": round(L_m, 4),
        "aspect_l_over_h": round(ratio, 4),
        "y_range_m": [round(-0.5 * L_m, 4), round(+0.5 * L_m, 4)],
        "z_range_m": [0.0, round(H_m, 4)],
        "palette_hex": hex_stops,
        "ascii_silhouette": ascii_rows,
    }
    (out_p / "photo_blueprint.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def project_photo_albedo(
    vertices: np.ndarray,
    base_albedo: np.ndarray,
    photo_path: str | Path,
    blend: float = 0.42,
) -> np.ndarray:
    """Projette proprement les nuances chromatiques réelles d'une photo de profil/3-quarts
    gauche (`-Y` à gauche, `+Y` à droite, `+Z` en haut) sur les sommets High-Poly en remplissant
    les zones hors-masque par plus proche voisin interne (zéro halo blanc du fond !)."""
    data = extract_subject_mask_and_crop(photo_path)
    crop_rgb = data["crop_rgb"]
    mask = ndimage.binary_erosion(data["crop_mask"], iterations=2)
    if mask.sum() < 24:
        mask = data["crop_mask"]

    # Remplit tout l'arrière-plan par le pixel interne valide le plus proche (`distance_transform_edt`) !
    _, nearest_idx = ndimage.distance_transform_edt(~mask, return_indices=True)
    safe_rgb = crop_rgb[nearest_idx[0], nearest_idx[1]]

    v = np.asarray(vertices, dtype=np.float64)
    vmin = v.min(axis=0)
    vmax = v.max(axis=0)
    span_y = max(float(vmax[1] - vmin[1]), 1e-6)
    span_z = max(float(vmax[2] - vmin[2]), 1e-6)

    bh, bw, _ = safe_rgb.shape
    u_px = np.clip((v[:, 1] - vmin[1]) / span_y, 0.0, 1.0) * (bw - 1)
    v_px = np.clip(1.0 - (v[:, 2] - vmin[2]) / span_z, 0.0, 1.0) * (bh - 1)
    sampled = safe_rgb[np.round(v_px).astype(np.int32), np.round(u_px).astype(np.int32)]

    k = float(np.clip(blend, 0.0, 1.0))
    return np.clip((1.0 - k) * base_albedo + k * sampled, 0.02, 0.92).astype(np.float32)


def verify_photo_match(
    photo_path: str | Path,
    asset_path: str | Path,
    out_png: str | Path,
    azimuth_deg: float = 72.0,
    elevation_deg: float = 9.0,
    fov: float = 34.0,
) -> dict:
    """Rend `asset_path` sous l'angle caméra de la photo et produit la planche comparative
    obligatoire `[PHOTO DE RÉFÉRENCE | MODÈLE 3D GÉNÉRÉ]` + IoU de silhouette globale."""
    import trimesh
    import renderer as rn

    ref = extract_subject_mask_and_crop(photo_path)
    ref_rgb = ref["crop_rgb"]
    ref_mask = ref["crop_mask"]

    sc = trimesh.load(asset_path, force="scene")
    ren_im = rn.render_view(sc, azimuth_deg=azimuth_deg, elevation_deg=elevation_deg, size=720, fov=fov)
    ren_data = extract_subject_mask_and_crop(_save_tmp_pil(ren_im, Path(out_png).parent / ".tmp_verify_render.png"))

    # Redimensionne les deux silhouettes cadrées sur une boîte commune pour mesurer l'IoU de forme !
    m_a = np.asarray(Image.fromarray((ref_mask * 255).astype(np.uint8)).resize((256, 256), Image.Resampling.NEAREST)) > 127
    m_b = np.asarray(Image.fromarray((ren_data["crop_mask"] * 255).astype(np.uint8)).resize((256, 256), Image.Resampling.NEAREST)) > 127
    iou = float(np.logical_and(m_a, m_b).sum() / max(np.logical_or(m_a, m_b).sum(), 1))

    # Planche comparative côte-à-côte haute résolution
    panel_w, panel_h = 680, 560
    sheet = Image.new("RGB", (panel_w * 2 + 36, panel_h + 76), (18, 21, 28))
    dr = ImageDraw.Draw(sheet)

    def _fit_panel(im_src: Image.Image) -> Image.Image:
        box = Image.new("RGB", (panel_w, panel_h), (242, 243, 246))
        s = min((panel_w - 40) / max(im_src.width, 1), (panel_h - 40) / max(im_src.height, 1))
        nw, nh = max(int(round(im_src.width * s)), 1), max(int(round(im_src.height * s)), 1)
        rs = im_src.resize((nw, nh), Image.Resampling.LANCZOS)
        box.paste(rs, ((panel_w - nw) // 2, (panel_h - nh) // 2))
        return box

    ref_pil = Image.fromarray((np.clip(ref_rgb, 0.0, 1.0) * 255).astype(np.uint8))
    ren_crop_pil = Image.fromarray((np.clip(ren_data["crop_rgb"], 0.0, 1.0) * 255).astype(np.uint8))

    sheet.paste(_fit_panel(ref_pil), (12, 58))
    sheet.paste(_fit_panel(ren_crop_pil), (panel_w + 24, 58))
    dr.text(
        (18, 18),
        f"PHOTO DE REFERENCE (L/H = {ref['aspect_l_over_h']:.2f})   vs   MODELE 3D GENERE (L/H = {ren_data['aspect_l_over_h']:.2f}  |  Silhouette IoU = {iou:.2f})",
        fill=(238, 244, 255),
    )
    out_p = Path(out_png)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_p)
    return {
        "out_png": str(out_p),
        "ref_aspect": round(ref["aspect_l_over_h"], 4),
        "model_aspect": round(ren_data["aspect_l_over_h"], 4),
        "bbox_iou": round(iou, 4),
    }


def _save_tmp_pil(im: Image.Image, tmp_p: Path) -> Path:
    tmp_p.parent.mkdir(parents=True, exist_ok=True)
    im.save(tmp_p)
    return tmp_p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_in = sub.add_parser("inspect", help="Extrait le blueprint métrique gradué + la vraie palette depuis une photo")
    p_in.add_argument("photo")
    p_in.add_argument("-o", "--out", default="exports/photo_blueprint")
    p_in.add_argument("--height", type=float, default=0.40)

    p_ve = sub.add_parser("verify", help="Compare côte-à-côte la photo de référence et le modèle 3D généré")
    p_ve.add_argument("photo")
    p_ve.add_argument("asset")
    p_ve.add_argument("-o", "--out", default="exports/photo_match.png")
    p_ve.add_argument("--az", type=float, default=-72.0)
    p_ve.add_argument("--el", type=float, default=9.0)
    p_ve.add_argument("--fov", type=float, default=34.0)

    args = ap.parse_args(argv)
    if args.cmd == "inspect":
        res = inspect_photo(args.photo, args.out, target_height=args.height)
        print(f"Blueprint écrit : {res['blueprint_png']} | L/H = {res['aspect_l_over_h']} | palette = {res['palette_hex']}")
        for line in res["ascii_silhouette"]:
            print(line)
        return 0
    if args.cmd == "verify":
        res = verify_photo_match(args.photo, args.asset, args.out, azimuth_deg=args.az, elevation_deg=args.el, fov=args.fov)
        print(json.dumps(res, ensure_ascii=False))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
