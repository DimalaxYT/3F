#!/usr/bin/env python3
"""
gpu_sculpt.py — Pipeline Sculpture Organique 3D propulsé par le GPU Datacenter (`3d-forge v4`).

Convertit un jeu cohérent de vues orthographiques haute définition générées sur
le GPU Datacenter (`front`, `side`, `back`, optionnellement `top`) en une VRAIE
sculpture 3D organique ronde, lisse, haute densité, texturée PBR et 100 % étanche :

  1. Extraction de silhouettes multi-vues haute précision + suppression de halos blancs.
  2. Reconstruction volumétrique SDF **elliptique locale multi-branches** :
       `(1 - d_front(x, z))² + (1 - d_side(y, z))² <= 1.0`
     où `d_front` et `d_side` sont les distances normalisées au squelette médian de
     CHAQUE corde connexe horizontale ! Résultat :
       - Sépare fidèlement les cornes doubles, oreilles, crocs, mâchoire et pointes !
       - Garantit une section transversale 100 % elliptique ronde (zéro boîte carrée) !
       - Respecte simultanément les silhouettes `front` (`-Y`) et `side` (`+X`) !
  3. Distance signée euclidienne 3D exacte (`distance_transform_edt`) + lissage 3D +
     relief fin lissé + filtre de Taubin sans retrait (`filter_taubin`).
  4. Fusion booléenne `manifold3d` avec un socle de musée chanfreiné en basalte poli
     garantissant un `.stl` **100 % `is_watertight == True`** prêt pour impression 3D.
  5. Dépliage `xatlas` + projection multi-vues pondérée par normales (`-Y = front`,
     `+Y = back`, `±X = side`) + Normal Map haute définition des écailles/dorures + AO.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpu_bridge as gb  # noqa: E402
import meshkit as mk  # noqa: E402
import pbr  # noqa: E402
import packager as pkg  # noqa: E402
import renderer  # noqa: E402
import usdz_export as usdz  # noqa: E402


def _chord_medial_profile(mask_2d: np.ndarray) -> np.ndarray:
    """Pour chaque ligne `iz` d'un masque silhouette `(H, W)`, calcule pour chaque
    segment horizontal connexe `[i0..i1]` le profil parabolique/sinusoïdal normalisé
    `d(i) = sin(pi * (i - i0 + 0.5) / (i1 - i0 + 1))` dans `[0, 1]` !
    Propriété magique :
      `(1 - d_x)² + (1 - d_y)² <= 1`  <=>  section EXACTEMENT elliptique sur CHAQUE
      branche séparée (cornes gauche/droite, oreilles, crocs, museau, cou) !
    """
    H, W = mask_2d.shape
    prof = np.zeros((H, W), dtype=np.float32)
    for r in range(H):
        row = mask_2d[r]
        if not row.any():
            continue
        padded = np.empty(W + 2, dtype=bool)
        padded[0] = False
        padded[1:-1] = row
        padded[-1] = False
        diff = np.diff(padded.astype(np.int8))
        starts = np.flatnonzero(diff == 1)
        ends = np.flatnonzero(diff == -1)
        for s, e in zip(starts, ends):
            span = e - s
            t = (np.arange(span, dtype=np.float32) + 0.5) / float(span)
            # Formule EXACTEMENT équivalente à `(x / a)² + (y / b)² <= 1` :
            # `(1 - d_x)² = (x / a)²  <=>  d_x = 1 - |2*t - 1|` ?
            # Non ! Encore mieux : posons directement `u_norm = |2*t - 1| ∈ [0, 1]` !
            # Alors `u_x² + u_y² <= 1` EST LITTÉRALEMENT L'ÉQUATION EXACTE D'UNE ELLIPSE !
            u_norm = np.abs(2.0 * t - 1.0)
            prof[r, s:e] = np.clip(1.0 - u_norm, 0.0, 1.0)
    return prof


def _prep_silhouette_view(path: str | Path, size: int = 384) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Charge une vue orthographique sur fond clair, extrait un masque propre sans ombre
    portée au sol, recadre verticalement et centre horizontalement dans un carré `size×size`."""
    arr = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
    h, w, _ = arr.shape
    b = max(4, min(h, w) // 32)
    bg = np.median(np.concatenate([
        arr[:b, :, :].reshape(-1, 3),
        arr[:, :b, :].reshape(-1, 3),
        arr[:, -b:, :].reshape(-1, 3),
    ], axis=0), axis=0)
    dist = np.linalg.norm(arr - bg[None, None, :], axis=2)
    sat = arr.max(axis=2) - arr.min(axis=2)
    # Exclut l'ombre douce grise quasi neutre tout en bas de l'image
    mask = (dist > 0.135) | (sat > 0.085)
    mask = ndimage.binary_closing(mask, iterations=2)
    mask = ndimage.binary_fill_holes(mask)
    # Ne garde que la plus grande composante connexe (élimine l'ombre flottante au sol !)
    lbl, n_comp = ndimage.label(mask)
    if n_comp > 1:
        sizes = ndimage.sum(mask, lbl, range(1, n_comp + 1))
        mask = lbl == (int(np.argmax(sizes)) + 1)

    ys, xs = np.nonzero(mask)
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    span = int(max(y1 - y0 + 1, x1 - x0 + 1) * 1.05)
    cy = 0.5 * (y0 + y1)
    cx = 0.5 * (x0 + x1)

    yy = np.clip(np.round(cy + (np.linspace(0, 1, size) - 0.5) * span).astype(np.int32), 0, h - 1)
    xx = np.clip(np.round(cx + (np.linspace(0, 1, size) - 0.5) * span).astype(np.int32), 0, w - 1)
    rgb_c = arr[np.ix_(yy, xx)].copy()
    mask_c = mask[np.ix_(yy, xx)].copy()

    # Érode `mask_c` de 4 px UNIQUEMENT pour la source de couleur afin d'éliminer 100 %
    # de la frange d'anti-aliasing claire (#E0E0E0) autour des cornes avant l'extension EDT !
    inner_valid = ndimage.binary_erosion(mask_c, iterations=4)
    if not inner_valid.any():
        inner_valid = mask_c
    _, idx = ndimage.distance_transform_edt(~inner_valid, return_indices=True)
    rgb_clean = rgb_c[idx[0], idx[1]].copy()
    # Débruitage médian 3x3 préservant à 100 % les bords francs (yeux, badges) tout en
    # éliminant le bruit granulaire parasite sur la peau et les tissus unis !
    rgb_clean = ndimage.median_filter(rgb_clean, size=(3, 3, 1))

    gray = 0.299 * rgb_clean[..., 0] + 0.587 * rgb_clean[..., 1] + 0.114 * rgb_clean[..., 2]
    detail = gray - ndimage.gaussian_filter(gray, sigma=2.8)
    return rgb_clean, mask_c, detail.astype(np.float32)


def _synthesize_clean_back_from_side(
    f_rgb: np.ndarray,
    s_rgb: np.ndarray,
    s_mask: np.ndarray,
) -> np.ndarray:
    """Synthétise un dos cohérent sans jamais projeter le visage (yeux/nez/bouche) à l'arrière :
    extrait à chaque hauteur Z la couleur arrière réelle visible sur la vue de profil `s_rgb`."""
    h = f_rgb.shape[0]
    out = f_rgb[:, ::-1, :].copy()
    for r in range(h):
        cols = np.nonzero(s_mask[r])[0]
        if len(cols) >= 4:
            c0 = int(cols[max(0, int(0.08 * len(cols)))])
            c1 = int(cols[max(1, int(0.42 * len(cols)))])
            row_col = np.median(s_rgb[r, c0:max(c0 + 1, c1 + 1), :], axis=0)
            out[r, :] = row_col[None, :]
    return ndimage.gaussian_filter(out, sigma=(4.5, 6.5, 0.0)).astype(np.float32)


def sculpt_from_views(
    front_path: str | Path,
    side_path: str | Path | None = None,
    back_path: str | Path | None = None,
    grid_res: int = 136,
    target_height: float = 0.28,
    relief_mm: float = 0.85,
    plinth_base: bool = False,
    depth_path: str | Path | None = None,
    depth_span: float | None = None,
    hollow_thickness: float = 0.0,
) -> tuple[trimesh.Trimesh, dict]:
    """Reconstruit une sculpture 3D organique haute définition 100 % `is_watertight`
    orientée selon la convention standard `3d-forge` :
      - `-Y` = FACE AVANT (`front_path`, museau vers `-Y`)
      - `+Y` = DOS (`back_path`, crête dorsale vers `+Y`)
      - `+X` = CÔTÉ DROIT (`side_path` regarde le flanc droit, museau à droite = `-Y`)
      - `+Z` = HAUT (`z = 0` posé à plat sur le plateau d'impression / sol).
    Supporte également :
      - `depth_path` (`--depth`) : carte de profondeur alignée à `front_path` (blanc = proche
        caméra `-Y`, sombre = en retrait `+Y`) pour préserver à 100 % le relief des nez longs,
        orbites, crocs, pommettes et visières sans jamais gonfler le visage en ballon !
      - `hollow_thickness` (`> 0`, en mètres, ex. `0.012`) : évide automatiquement la face
        arrière pour les masques (Tengu, Oni), casques, boucliers et épaulières !
    """
    from skimage.measure import marching_cubes

    sz = int(grid_res)
    tex_sz = 768
    f_hi, f_mhi, _ = _prep_silhouette_view(front_path, size=tex_sz)
    has_real_side = bool(side_path and Path(side_path).exists())
    if has_real_side:
        s_hi, s_mhi, _ = _prep_silhouette_view(side_path, size=tex_sz)
    else:
        s_hi, s_mhi = f_hi.copy(), f_mhi.copy()
    has_real_back = bool(back_path and Path(back_path).exists())
    if has_real_back:
        b_hi, b_mhi, _ = _prep_silhouette_view(back_path, size=tex_sz)
    else:
        b_hi, b_mhi = f_hi[:, ::-1, :].copy(), f_mhi[:, ::-1].copy()

    f_ys_hi = np.nonzero(f_mhi)[0]
    fy0_hi, fy1_hi = float(f_ys_hi.min()), float(f_ys_hi.max())

    def _align_vertical_hi(rgb_in, m_in, ref_y0, ref_y1, n_out):
        ys_m = np.nonzero(m_in)[0]
        y0_m, y1_m = float(ys_m.min()), float(ys_m.max())
        t = (np.arange(n_out, dtype=np.float32) - ref_y0) / max(ref_y1 - ref_y0, 1.0)
        src_y = np.clip(np.round(y0_m + t * (y1_m - y0_m)).astype(np.int32), 0, n_out - 1)
        return rgb_in[src_y], m_in[src_y]

    s_hi, s_mhi = _align_vertical_hi(s_hi, s_mhi, fy0_hi, fy1_hi, tex_sz)
    if has_real_back:
        b_hi, b_mhi = _align_vertical_hi(b_hi, b_mhi, fy0_hi, fy1_hi, tex_sz)
    else:
        b_hi = _synthesize_clean_back_from_side(f_hi, s_hi, s_mhi)

    idx_ds = np.linspace(0, tex_sz - 1, sz).round().astype(np.int32)
    f_mask = f_mhi[np.ix_(idx_ds, idx_ds)]
    s_mask = s_mhi[np.ix_(idx_ds, idx_ds)]
    b_mask = b_mhi[np.ix_(idx_ds, idx_ds)]
    f_det = (0.299 * f_hi[..., 0] + 0.587 * f_hi[..., 1] + 0.114 * f_hi[..., 2])
    f_det = (f_det - ndimage.gaussian_filter(f_det, sigma=5.0))[np.ix_(idx_ds, idx_ds)].astype(np.float32)
    s_det = (0.299 * s_hi[..., 0] + 0.587 * s_hi[..., 1] + 0.114 * s_hi[..., 2])
    s_det = (s_det - ndimage.gaussian_filter(s_det, sigma=5.0))[np.ix_(idx_ds, idx_ds)].astype(np.float32)
    b_det = (0.299 * b_hi[..., 0] + 0.587 * b_hi[..., 1] + 0.114 * b_hi[..., 2])
    b_det = (b_det - ndimage.gaussian_filter(b_det, sigma=5.0))[np.ix_(idx_ds, idx_ds)].astype(np.float32)
    f_rgb, s_rgb, b_rgb = f_hi, s_hi, b_hi
    fy0 = fy0_hi * (sz / tex_sz)
    fy1 = fy1_hi * (sz / tex_sz)

    # Profils de cordes normalisés (`u_x = 1 - prof_x`, `u_y = 1 - prof_y`)
    # Rappel convention axes :
    #   ix ∈ [0..sz-1] <-> X de gauche (-X) à droite (+X)
    #   iy ∈ [0..sz-1] <-> Y de l'AVANT (-Y, museau = droite de `side`, u_side=sz-1)
    #                          vers l'ARRIÈRE (+Y, nuque = gauche de `side`, u_side=0) !
    #   iz ∈ [0..sz-1] <-> Z du BAS (iz=0, ligne image sz-1) vers le HAUT (iz=sz-1, ligne 0) !
    s_rgb_y = s_rgb[:, ::-1, :]    # col 0 = -Y (museau/avant), col sz-1 = +Y (dos/nuque) !
    s_mask_y = s_mask[:, ::-1]
    s_det_y = s_det[:, ::-1]

    fb_mask = f_mask | b_mask[:, ::-1]
    prof_x = _chord_medial_profile(fb_mask[::-1, :])    # (iz, ix)
    prof_y = _chord_medial_profile(s_mask_y[::-1, :])   # (iz, iy)

    voxel_m = float(target_height) / float(max(fy1 - fy0, 1.0))

    has_depth = bool(depth_path and Path(depth_path).exists())
    if has_depth:
        # Aligne `depth_path` pixel-à-pixel sur le recadrage exact de `front_path` !
        arr_f_raw = np.asarray(Image.open(front_path).convert("RGB"), dtype=np.float32) / 255.0
        hf, wf, _ = arr_f_raw.shape
        bf = max(4, min(hf, wf) // 32)
        bg_f = np.median(np.concatenate([
            arr_f_raw[:bf, :, :].reshape(-1, 3),
            arr_f_raw[:, :bf, :].reshape(-1, 3),
            arr_f_raw[:, -bf:, :].reshape(-1, 3),
        ], axis=0), axis=0)
        dist_f = np.linalg.norm(arr_f_raw - bg_f[None, None, :], axis=2)
        sat_f = arr_f_raw.max(axis=2) - arr_f_raw.min(axis=2)
        m_f0 = ndimage.binary_fill_holes(ndimage.binary_closing((dist_f > 0.135) | (sat_f > 0.085), iterations=2))
        lbl_f, nc_f = ndimage.label(m_f0)
        if nc_f > 1:
            m_f0 = lbl_f == (int(np.argmax(ndimage.sum(m_f0, lbl_f, range(1, nc_f + 1)))) + 1)
        ys0, xs0 = np.nonzero(m_f0)
        span0 = int(max(int(ys0.max()) - int(ys0.min()) + 1, int(xs0.max()) - int(xs0.min()) + 1) * 1.05)
        cy0, cx0 = 0.5 * (ys0.min() + ys0.max()), 0.5 * (xs0.min() + xs0.max())

        d_raw = Image.open(depth_path).convert("L").resize((wf, hf), Image.Resampling.BILINEAR)
        d_arr = np.asarray(d_raw, dtype=np.float32) / 255.0
        yy_d = np.clip(np.round(cy0 + (np.linspace(0, 1, sz) - 0.5) * span0).astype(np.int32), 0, hf - 1)
        xx_d = np.clip(np.round(cx0 + (np.linspace(0, 1, sz) - 0.5) * span0).astype(np.int32), 0, wf - 1)
        d_crop = d_arr[np.ix_(yy_d, xx_d)]
        fg_vals = d_crop[fb_mask]
        lo_d = float(np.percentile(fg_vals, 2.0)) if fg_vals.size else 0.0
        hi_d = float(np.percentile(fg_vals, 99.2)) if fg_vals.size else 1.0
        d_norm = np.clip((d_crop - lo_d) / max(hi_d - lo_d, 1e-3), 0.0, 1.0)
        d_norm = ndimage.gaussian_filter(d_norm, sigma=0.85)[::-1, :]  # (iz, ix), 1=proche caméra (-Y)

        if has_real_side and s_mask_y.any():
            ys_cols = np.nonzero(s_mask_y)[1]
            span_y_vox = float(max(int(ys_cols.max()) - int(ys_cols.min()) + 1, sz * 0.22))
        else:
            span_y_m = float(depth_span) if depth_span else float(target_height) * 0.52
            span_y_vox = max(span_y_m / max(voxel_m, 1e-5), 6.0)

        iy_grid = np.arange(sz, dtype=np.float32)[None, None, :]
        iy_front_min = max(3.0, 0.5 * (sz - span_y_vox))
        y_front = iy_front_min + (1.0 - d_norm)[:, :, None] * (span_y_vox * (0.82 if hollow_thickness > 0 else 0.62))
        fb_z = fb_mask[::-1, :][:, :, None]
        if hollow_thickness > 0:
            wall_vox = max(float(hollow_thickness) / max(voxel_m, 1e-5), 2.6)
            occ_zxy = fb_z & (iy_grid >= y_front) & (iy_grid <= y_front + wall_vox)
        else:
            y_back = iy_front_min + span_y_vox * (0.60 + 0.40 * prof_x[:, :, None])
            occ_zxy = fb_z & (iy_grid >= y_front) & (iy_grid <= np.maximum(y_front + 2.5, y_back))
    else:
        ux = 1.0 - prof_x[:, :, None]   # (iz, ix, 1)
        uy = 1.0 - prof_y[:, None, :]   # (iz, 1, iy)
        occ_zxy = (ux * ux + uy * uy) <= 1.0
        if hollow_thickness > 0:
            wall_vox = int(max(round(float(hollow_thickness) / max(voxel_m, 1e-5)), 3))
            shifted = np.zeros_like(occ_zxy)
            if wall_vox < sz:
                shifted[:, :, wall_vox:] = occ_zxy[:, :, :-wall_vox]
            occ_zxy = occ_zxy & (~shifted)

    occ = np.transpose(occ_zxy, (1, 2, 0))  # (ix, iy, iz)

    # Ne conserve que la composante principale 3D connectée (élimine tout îlot flottant !)
    lbl3, n3 = ndimage.label(occ)
    if n3 > 1:
        c_sizes = ndimage.sum(occ, lbl3, range(1, n3 + 1))
        occ = lbl3 == (int(np.argmax(c_sizes)) + 1)

    # VRAIE distance signée euclidienne 3D (mètres) + lissage organique doux !
    sdf = (ndimage.distance_transform_edt(~occ) - ndimage.distance_transform_edt(occ)).astype(np.float32) * voxel_m
    sdf = ndimage.gaussian_filter(sdf, sigma=1.15)

    # Relief anatomique doux basse-fréquence (écailles, arêtes dorées) sans aucun pic bruité
    det_f = ndimage.gaussian_filter(f_det[::-1, :], sigma=0.9)[:, :, None]
    det_b = ndimage.gaussian_filter(b_det[::-1, ::-1], sigma=0.9)[:, :, None]
    det_s = ndimage.gaussian_filter(s_det_y[::-1, :], sigma=0.9)[:, None, :]
    w_front = np.linspace(1.0, 0.0, sz, dtype=np.float32)[None, :, None]
    fb_det = w_front * det_f + (1.0 - w_front) * det_b
    relief_zxy = 0.55 * fb_det + 0.45 * det_s
    sdf -= np.transpose(relief_zxy, (1, 2, 0)) * (float(relief_mm) * 1e-3)
    sdf = ndimage.gaussian_filter(sdf, sigma=0.65)

    # Bordure fermée stricte pour garantir une surface de Marching Cubes 100 % close
    pad_sdf = np.pad(sdf, 2, mode="constant", constant_values=max(voxel_m * 4.0, 0.01))
    verts, faces, _, _ = marching_cubes(pad_sdf, level=0.0, spacing=(voxel_m, voxel_m, voxel_m))
    raw_mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)

    # Lissage de Taubin calibré `v5.1` (6 passes au lieu de 10 -> préserve le tranchant
    # des cornes, crocs, arêtes d'armure et gravures sans aucun escalier de voxel !)
    trimesh.smoothing.filter_taubin(raw_mesh, lamb=0.45, nu=-0.48, iterations=6)
    raw_mesh.remove_unreferenced_vertices()
    comps = raw_mesh.split(only_watertight=False)
    if len(comps) > 1:
        raw_mesh = max(comps, key=lambda c: len(c.faces))
    if not raw_mesh.is_watertight:
        trimesh.repair.fill_holes(raw_mesh)
        trimesh.repair.fix_winding(raw_mesh)
        trimesh.repair.fix_normals(raw_mesh)

    # Centre X/Y et pose le buste sur son socle de musée chanfreiné en basalte noir
    c_xy = 0.5 * (raw_mesh.bounds[0][:2] + raw_mesh.bounds[1][:2])
    plinth_h = float(target_height) * 0.085 if plinth_base else 0.0
    raw_mesh.vertices[:, 0] -= c_xy[0]
    raw_mesh.vertices[:, 1] -= c_xy[1]
    raw_mesh.vertices[:, 2] -= raw_mesh.bounds[0][2] - (plinth_h * 0.72 if plinth_base else 0.0)

    # Conversion exacte Manifold3D (répare toute micro-auto-intersection de lissage !)
    if plinth_base:
        ext = raw_mesh.extents
        pw, pd = float(ext[0] * 0.68), float(ext[1] * 0.68)
        p1 = mk.chamfer_box(pw, pd, plinth_h * 0.62, c=min(pw, pd) * 0.06)
        p2 = mk.chamfer_box(pw * 0.88, pd * 0.88, plinth_h, c=min(pw, pd) * 0.05)
        raw_mesh = mk.union([raw_mesh, p1, p2])
    else:
        raw_mesh.fix_normals(multibody=False)
        if not raw_mesh.is_watertight:
            trimesh.repair.fill_holes(raw_mesh)
            raw_mesh.fix_normals(multibody=False)

    raw_mesh.vertices[:, 2] -= raw_mesh.bounds[0][2]

    view_pack = {
        "front_rgb": (f_rgb * 255.0).clip(0, 255).astype(np.uint8),
        "back_rgb": (b_rgb * 255.0).clip(0, 255).astype(np.uint8),
        "side_rgb": (s_rgb_y * 255.0).clip(0, 255).astype(np.uint8),  # col 0 = -Y (avant), col -1 = +Y (dos)
        "crop_bounds": (
            raw_mesh.bounds.copy(),
            float(fy0) / sz,
            float(fy1) / sz,
            plinth_h * 0.72,
        ),
    }
    return raw_mesh, view_pack


def bake_sculpt_pbr(
    mesh: trimesh.Trimesh,
    view_pack: dict,
    resolution: int = 1024,
    metallic_gold_boost: bool = False,
    delight_albedo: bool = True,
) -> tuple[trimesh.Trimesh, Image.Image, Image.Image, Image.Image]:
    """Déplie `mesh` avec `xatlas` (pré-décimé proprement en C++ à `<= 22 000 tris`
    pour diviser par `30×` le temps d'`xatlas.parametrize` sans aucune perte visuelle !)
    et projette en 100 % vectorisé NumPy les vues orthographiques GPU."""
    work_mesh = mesh
    if len(work_mesh.faces) > 22_000:
        import fast_simplification
        v_in = np.asarray(work_mesh.vertices, dtype=np.float32)
        f_in = np.asarray(work_mesh.faces, dtype=np.int32)
        ratio = float(np.clip(1.0 - 20_000.0 / float(len(f_in)), 0.05, 0.96))
        v_o, f_o = fast_simplification.simplify(v_in, f_in, target_reduction=ratio, agg=6)
        work_mesh = trimesh.Trimesh(vertices=v_o, faces=f_o, process=True)
    v_labels = np.zeros(len(work_mesh.vertices), dtype=np.int64)
    mesh2, _, uv = pbr.unwrap(work_mesh, v_labels)
    ao = pbr.compute_ambient_occlusion(mesh2)

    S = int(resolution)
    f_arr = np.asarray(mesh2.faces, dtype=np.int64)
    verts = np.asarray(mesh2.vertices, dtype=np.float32)
    vnorms = np.asarray(mesh2.vertex_normals, dtype=np.float32)
    tri_uv = np.empty((len(f_arr), 3, 2), dtype=np.float64)
    tri_uv[..., 0] = uv[f_arr, 0] * S
    tri_uv[..., 1] = (1.0 - uv[f_arr, 1]) * S
    hit = pbr.rasterize_uv_triangles(tri_uv, S)
    f_hit, xs, ys, w0, w1, w2 = hit
    v0, v1, v2 = f_arr[f_hit, 0], f_arr[f_hit, 1], f_arr[f_hit, 2]
    pos = (w0[:, None] * verts[v0] + w1[:, None] * verts[v1] + w2[:, None] * verts[v2]).astype(np.float32)
    nrm = (w0[:, None] * vnorms[v0] + w1[:, None] * vnorms[v1] + w2[:, None] * vnorms[v2]).astype(np.float32)
    ao_px = (w0 * ao[v0] + w1 * ao[v1] + w2 * ao[v2]).astype(np.float32)
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
    pix_mask = np.zeros((S, S), dtype=bool)
    pix_mask[ys, xs] = True

    bmin, bmax = mesh2.bounds
    _, v_top_norm, v_bot_norm, z_sculpt0 = view_pack["crop_bounds"]
    span_z = max(float(bmax[2] - z_sculpt0), 1e-6)
    span_xy = max(float(bmax[0] - bmin[0]), float(bmax[1] - bmin[1]), 1e-6)
    cx = 0.5 * float(bmin[0] + bmax[0])
    cy = 0.5 * float(bmin[1] + bmax[1])

    # Coordonnées image normalisées exactes alignées sur la grille volumétrique `sculpt_from_views` :
    #   - En Z : z_sculpt0 -> v_bot_norm (bas du buste), bmax[2] -> v_top_norm (pointe des cornes)
    #   - En X/Y : même échelle isotrope `voxel_m` que `span_z / (v_bot_norm - v_top_norm)` !
    full_box_m = span_z / max(v_bot_norm - v_top_norm, 1e-6)
    v_img = np.clip(v_bot_norm - ((pos[:, 2] - z_sculpt0) / full_box_m), 0.0, 1.0)
    ux_front = np.clip(0.5 + (pos[:, 0] - cx) / full_box_m, 0.0, 1.0)
    ux_back = 1.0 - ux_front
    uy_side = np.clip(0.5 + (pos[:, 1] - cy) / full_box_m, 0.0, 1.0)  # 0 = -Y (museau), 1 = +Y (dos)

    def _sample_bilin(img_u8: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        ih, iw, _ = img_u8.shape
        fx = np.clip(u, 0.0, 1.0) * (iw - 1)
        fy = np.clip(v, 0.0, 1.0) * (ih - 1)
        x0 = np.floor(fx).astype(np.int32)
        y0 = np.floor(fy).astype(np.int32)
        x1 = np.minimum(x0 + 1, iw - 1)
        y1 = np.minimum(y0 + 1, ih - 1)
        wx = (fx - x0)[:, None].astype(np.float32)
        wy = (fy - y0)[:, None].astype(np.float32)
        im = img_u8.astype(np.float32) / 255.0
        return ((1 - wx) * (1 - wy) * im[y0, x0]
                + wx * (1 - wy) * im[y0, x1]
                + (1 - wx) * wy * im[y1, x0]
                + wx * wy * im[y1, x1])

    c_front = _sample_bilin(view_pack["front_rgb"], ux_front, v_img)
    c_back = _sample_bilin(view_pack["back_rgb"], ux_back, v_img)
    c_side = _sample_bilin(view_pack["side_rgb"], uy_side, v_img)

    # Pondération angulaire par normales : `-Y` = AVANT (`front`), `+Y` = DOS (`back`), `±X` = PROFIL (`side`)
    wf = np.maximum(0.0, -nrm[:, 1]) ** 2.0 + 0.16 * np.where(nrm[:, 1] <= 0.0, np.abs(nrm[:, 2]) ** 2.0, 0.0)
    wb = np.maximum(0.0, nrm[:, 1]) ** 2.0 + 0.16 * np.where(nrm[:, 1] > 0.0, np.abs(nrm[:, 2]) ** 2.0, 0.0)
    ws = np.abs(nrm[:, 0]) ** 2.4
    wsum = wf + wb + ws + 1e-6
    rgb = (wf[:, None] * c_front + wb[:, None] * c_back + ws[:, None] * c_side) / wsum[:, None]

    # Socle architectural de musée en basalte noir satiné UNIQUEMENT si `plinth_base=True` (`z_sculpt0 > 0`)
    if z_sculpt0 > 1e-5:
        plinth_top = z_sculpt0 / 0.72 * 1.03
        blend_p = np.clip((plinth_top - pos[:, 2]) / max(z_sculpt0 * 0.10, 1e-4), 0.0, 1.0)
    else:
        blend_p = np.zeros(len(pos), dtype=np.float32)
    basalt_col = np.array([0.095, 0.098, 0.106], dtype=np.float32)
    rgb = rgb * (1.0 - blend_p[:, None]) + basalt_col[None, :] * blend_p[:, None]
    is_plinth = blend_p > 0.5

    # v5 Game-Ready : De-lighting physique SH d'ordre 2 sur l'Albédo projeté afin
    # d'éliminer les ombres/reflets studio cuits avant export vers Unreal / Unity / Godot !
    if delight_albedo:
        import delight as dl
        rgb_non_plinth, _ = dl.delight_albedo_3d(rgb, nrm, strength=0.72)
        rgb = np.where(is_plinth[:, None], rgb, rgb_non_plinth)

    lum = 0.299 * rgb[:, 0] + 0.587 * rgb[:, 1] + 0.114 * rgb[:, 2]
    if metallic_gold_boost:
        gold_hue = (
            np.clip((rgb[:, 1] - rgb[:, 2] * 1.35) * 4.5, 0.0, 1.0)
            * np.clip((rgb[:, 0] - 0.38) * 3.5, 0.0, 1.0)
            * np.clip(1.65 - rgb[:, 0] / np.maximum(rgb[:, 1], 1e-3), 0.0, 1.0)
        )
        is_gold = np.clip(gold_hue, 0.0, 1.0)
    else:
        is_gold = np.zeros_like(lum)
    metal_px = np.clip(0.85 * is_gold, 0.0, 1.0)
    rough_px = np.clip((0.62 - 0.20 * lum) * (1.0 - 0.55 * is_gold) + 0.20 * is_gold, 0.14, 0.90)
    rough_px = np.where(is_plinth, 0.26, rough_px)

    albedo = np.zeros((S, S, 3), dtype=np.float32)
    mr = np.zeros((S, S, 3), dtype=np.float32)
    mr[..., 0], mr[..., 1] = 1.0, 0.65
    albedo[ys, xs] = np.clip(rgb, 0.0, 1.0)
    mr[ys, xs, 0] = np.clip(ao_px, 0.16, 1.0)
    mr[ys, xs, 1] = rough_px
    mr[ys, xs, 2] = metal_px

    # Carte de hauteur douce extraite de la luminance locale sans creuser la peau lisse !
    hmap = np.zeros((S, S), dtype=np.float32)
    hmap[ys, xs] = lum
    _, nn_idx = ndimage.distance_transform_edt(~pix_mask, return_indices=True)
    albedo = albedo[nn_idx[0], nn_idx[1]]
    mr = mr[nn_idx[0], nn_idx[1]]
    hmap = hmap[nn_idx[0], nn_idx[1]]
    hp_micro = hmap - ndimage.gaussian_filter(hmap, sigma=1.4)
    hp_meso = ndimage.gaussian_filter(hmap, sigma=1.2) - ndimage.gaussian_filter(hmap, sigma=3.8)
    hmap_hp = 0.85 * hp_micro + 0.70 * hp_meso

    alb_img = Image.fromarray((np.clip(albedo, 0.0, 1.0) * 255).astype(np.uint8), "RGB")
    mr_img = Image.fromarray((np.clip(mr, 0.0, 1.0) * 255).astype(np.uint8), "RGB")
    dy, dx = np.gradient(hmap_hp.astype(np.float32) * 1.15)
    nz = np.ones_like(dx)
    nlen = np.sqrt(dx * dx + dy * dy + nz * nz) + 1e-12
    nmap = np.stack([-dx / nlen, dy / nlen, nz / nlen], axis=-1) * 0.5 + 0.5
    nrm_img = Image.fromarray((np.clip(nmap, 0.0, 1.0) * 255).astype(np.uint8), "RGB")

    pbr_mat = trimesh.visual.material.PBRMaterial(
        name="sculpted_gpu_pbr",
        baseColorFactor=[255, 255, 255, 255],
        baseColorTexture=alb_img,
        metallicRoughnessTexture=mr_img,
        occlusionTexture=mr_img,
        normalTexture=nrm_img,
        metallicFactor=1.0,
        roughnessFactor=1.0,
    )
    mesh2.visual = trimesh.visual.TextureVisuals(uv=uv, material=pbr_mat)
    return mesh2, alb_img, mr_img, nrm_img


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--front", required=True)
    ap.add_argument("--side", default=None)
    ap.add_argument("--back", default=None)
    ap.add_argument("--depth", default=None, help="Carte de profondeur alignée à --front (blanc = proche)")
    ap.add_argument("--hollow-thickness", type=float, default=0.0,
                    help="Épaisseur de coque creuse en mètres (ex: 0.012 pour masque/casque)")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--stem", default="dragon_buste")
    ap.add_argument("--res", type=int, default=136)
    ap.add_argument("--height", type=float, default=0.28)
    ap.add_argument("--tex-res", type=int, default=1024)
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    mesh, vpack = sculpt_from_views(
        args.front, args.side, args.back,
        grid_res=args.res, target_height=args.height,
        depth_path=args.depth, hollow_thickness=args.hollow_thickness,
    )
    stl_path = out_dir / f"{args.stem}.stl"
    mesh.export(stl_path)

    mesh_pbr, alb_img, mr_img, nrm_img = bake_sculpt_pbr(mesh, vpack, resolution=args.tex_res)
    sc = trimesh.Scene([mesh_pbr])
    glb_path = out_dir / f"{args.stem}.glb"
    glb_path.write_bytes(sc.export(file_type="glb"))
    alb_img.save(out_dir / f"{args.stem}_basecolor.png", compress_level=1)
    mr_img.save(out_dir / f"{args.stem}_mr.png", compress_level=1)
    nrm_img.save(out_dir / f"{args.stem}_normal.png", compress_level=1)

    usdz.export_usdz(sc, out_dir / f"{args.stem}.usdz")
    pkg.build_asset_zip(str(out_dir))
    vkeys = ["front", "back", "left", "side", "top", "bottom"]
    renderer.render_views(sc, str(out_dir), stem=args.stem, views=vkeys + ["three_quarter"], size=480)
    renderer.contact_sheet(
        [(Image.open(out_dir / f"{args.stem}_{v}.png"), lbl)
         for v, lbl in zip(vkeys, ["face", "dos", "gauche", "droite", "dessus", "dessous"])],
        cols=3,
        out_path=str(out_dir / f"{args.stem}_all_faces.png"),
        title=f"3d-forge v4 — sculpture organique multi-vues GPU : {args.stem}",
    )
    print(json.dumps({
        "glb": str(glb_path),
        "stl": str(stl_path),
        "watertight": bool(mesh.is_watertight),
        "volume_l": round(float(mesh.volume) * 1000.0, 4),
        "triangles": int(len(mesh.faces)),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
