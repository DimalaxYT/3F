#!/usr/bin/env python3
"""gpu_bridge.py — Pont entre la géométrie 3D exacte (CPU : manifold3d + xatlas)
et le GPU de datacenter du modèle hôte (`generate_image`).

Résout la frontière matérielle fondamentale d'un skill exécuté en sandbox :
  - Le Python du bac à sable tourne sur VM CPU isolée (`cuda_available: false`),
    parfaite pour le CSG exact (`manifold3d`), le dépliage `xatlas`, le baking UV
    vectorisé et le lancer de rayons GGX + HDRI + SSAO.
  - Les modèles de diffusion du datacenter de l'agent (`generate_image`) tournent
    sur **GPU de datacenter**, zéro GPU requis côté utilisateur, avec une richesse
    de micro-matière photographique (grain de forge, piqûres d'oxyde, cuir usé,
    fibre de bois, boue séchée, anodisation, reflets d'atelier) impossible à
    synthétiser par seul bruit de Perlin CPU.

Trois commandes complémentaires :
  1. `prepare` : rend les guides géométriques exacts d'un `.glb` (rendu studio GGX,
     carte de profondeur normalisée, normales caméra, masque silhouette, matrices
     caméra exactes `cameras.json`) prêts à être passés en référence `images=[...]`
     à `generate_image` (GPU datacenter) pour un **rendu photo fidèle à la géométrie**
     (`photo_pass`) OU un **baking multi-vues dans l'atlas UV du `.glb`**.
  2. `bake-views` : reprojette `N` vues photoréalistes générées sur GPU datacenter
     directement dans l'atlas UV `xatlas` du `.glb` par z-buffer exact, pondération
     angulaire `cos^4`, dé-éclairage analytique (`albedo = radiance / irradiance`),
     extraction haute-fréquence de rugosité + normal map Sobel et occlusion ambiante
     cuite (`mr.r = AO`). **Le fichier `.glb` lui-même porte alors la texture IA !**
  3. `bake-tiles` : projette en triplanaire 3D sans couture un jeu de tuiles matière
     photoréalistes générées sur GPU datacenter (`assets/ai_materials/*.png`) par
     région sémantique (`labels` + `wear` + `AO` + `mud_splash`), puis ré-exporte
     `.glb` + `.usdz` + `preview.html` + rendus studio !

CLI :
    python scripts/gpu_bridge.py prepare model.glb -o work_gpu
    python scripts/gpu_bridge.py bake-views model.glb --cameras work_gpu/cameras.json --views v0.png v1.png -o model_ai.glb
    python scripts/gpu_bridge.py bake-tiles model.glb --spec ai_tex.json -o model_ai.glb
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
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pbr
import renderer


def _single_mesh_from_scene(scene_or_mesh) -> trimesh.Trimesh:
    if isinstance(scene_or_mesh, trimesh.Trimesh):
        return scene_or_mesh.copy()
    if hasattr(scene_or_mesh, "parts") and not hasattr(scene_or_mesh, "graph"):
        parts_colored = []
        for pm, pmat, _ in scene_or_mesh.parts:
            mc = pm.copy()
            col_u8 = np.clip(np.asarray(getattr(pmat, "color", [0.6, 0.6, 0.6]), dtype=np.float32)[:3] * 255.0, 0, 255).astype(np.uint8)
            mc.visual.vertex_colors = np.column_stack([
                np.tile(col_u8, (len(mc.vertices), 1)),
                np.full(len(mc.vertices), 255, dtype=np.uint8),
            ])
            parts_colored.append(mc)
        return trimesh.util.concatenate(parts_colored)
    geos = []
    for name in scene_or_mesh.graph.nodes_geometry:
        tf, gname = scene_or_mesh.graph[name]
        g = scene_or_mesh.geometry[gname].copy()
        g.apply_transform(tf)
        geos.append(g)
    if not geos:
        raise ValueError("aucun maillage dans la scène")
    return geos[0] if len(geos) == 1 else trimesh.util.concatenate(geos)


def prepare_guides(glb_path: str, outdir: str, views=None, size: int = 1024,
                   fov: float = 38.0) -> dict:
    """Exporte rendus studio GGX + cartes depth/normal/silhouette + `cameras.json`."""
    os.makedirs(outdir, exist_ok=True)
    scene = trimesh.load(glb_path, force="scene")
    parts = renderer._gather(scene)
    center, radius, _ = renderer._bounds(parts)
    dist = radius * 3.1

    views = views or {
        "hero": [42.0, 22.0],
        "front": [0.0, 12.0],
        "back": [180.0, 12.0],
        "side": [90.0, 12.0],
    }
    manifest = {
        "source_glb": os.path.abspath(glb_path),
        "size": int(size),
        "fov": float(fov),
        "center": center.tolist(),
        "radius": float(radius),
        "views": {},
    }
    for name, (az, el) in views.items():
        az_r, el_r = math.radians(az), math.radians(el)
        eye = center + dist * np.array([
            math.cos(el_r) * math.sin(az_r),
            -math.cos(el_r) * math.cos(az_r),
            math.sin(el_r),
        ])
        V = renderer._look_at(eye, center)
        P = renderer._perspective(fov, 1.0, radius * 0.1, radius * 12.0)
        PV = P @ V

        studio_p = os.path.join(outdir, f"guide_{name}_studio.png")
        depth_p = os.path.join(outdir, f"guide_{name}_depth.png")
        norm_p = os.path.join(outdir, f"guide_{name}_normal.png")
        sil_p = os.path.join(outdir, f"guide_{name}_mask.png")

        renderer.render_view(scene, az, el, size=size, fov=fov).save(studio_p)
        renderer.render_depth(scene, az, el, size=size, fov=fov).save(depth_p)
        renderer.render_normals(scene, az, el, size=size, fov=fov).save(norm_p)
        renderer.render_silhouette(scene, az, el, size=size, fov=fov).save(sil_p)

        manifest["views"][name] = {
            "azimuth_deg": float(az),
            "elevation_deg": float(el),
            "eye": eye.tolist(),
            "PV": PV.tolist(),
            "V": V.tolist(),
            "studio": studio_p,
            "depth": depth_p,
            "normal": norm_p,
            "mask": sil_p,
        }

    cam_json = os.path.join(outdir, "cameras.json")
    with open(cam_json, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


def _load_tile(path: str) -> np.ndarray:
    """Charge une tuile image sRGB `[0..1]` `(H, W, 3)`."""
    im = Image.open(path).convert("RGB")
    return np.asarray(im, dtype=np.float64) / 255.0


def _triplanar_sample_tile(tile: np.ndarray, pos: np.ndarray, nrm: np.ndarray,
                           scale: float = 2.0) -> np.ndarray:
    """Projection triplanaire 3D sans couture d'une tuile texture GPU `(H, W, 3)`
    avec miroir périodique doux pour éliminer toute discontinuité aux bords."""
    H, W, _ = tile.shape
    w = np.abs(nrm) ** 4.0
    w /= np.clip(w.sum(axis=-1, keepdims=True), 1e-9, None)

    def _samp2d(u, v):
        # Repliement triangle (mirror wrap) -> 100% continu même si la tuile a un léger gradient
        uf = np.mod(u * scale, 2.0)
        vf = np.mod(v * scale, 2.0)
        uf = np.where(uf > 1.0, 2.0 - uf, uf)
        vf = np.where(vf > 1.0, 2.0 - vf, vf)
        fx = np.clip(uf * (W - 1), 0.0, W - 1.001)
        fy = np.clip(vf * (H - 1), 0.0, H - 1.001)
        x0 = fx.astype(np.int64); y0 = fy.astype(np.int64)
        x1 = np.minimum(x0 + 1, W - 1); y1 = np.minimum(y0 + 1, H - 1)
        tx = (fx - x0)[..., None]; ty = (fy - y0)[..., None]
        c00 = tile[y0, x0]; c10 = tile[y0, x1]
        c01 = tile[y1, x0]; c11 = tile[y1, x1]
        return (c00 * (1 - tx) + c10 * tx) * (1 - ty) + (c01 * (1 - tx) + c11 * tx) * ty

    cx = _samp2d(pos[:, 1], pos[:, 2])
    cy = _samp2d(pos[:, 0], pos[:, 2])
    cz = _samp2d(pos[:, 0], pos[:, 1])
    return w[:, 0:1] * cx + w[:, 1:2] * cy + w[:, 2:3] * cz


def _assign_z_regions(mesh: trimesh.Trimesh, spec: dict) -> np.ndarray:
    """Assigne à chaque sommet l'indice de sa région `[z0, z1]` normalisée."""
    z = mesh.vertices[:, 2]
    z0, z1 = float(z.min()), float(z.max())
    zn = (z - z0) / max(z1 - z0, 1e-6)
    labels = np.zeros(len(z), dtype=np.int64)
    for idx, reg in enumerate(spec.get("regions", [])):
        lo_z, hi_z = reg.get("z", [0.0, 1.0])
        labels[(zn >= lo_z - 1e-6) & (zn <= hi_z + 1e-6)] = idx
    return labels


def bake_ai_tiles_to_mesh(mesh: trimesh.Trimesh, spec: dict,
                          labels: np.ndarray | None = None) -> tuple[trimesh.Trimesh, dict]:
    """Bake dans un vrai atlas UV `xatlas` des tuiles matière générées sur GPU
    datacenter (`generate_image`), combinées avec :
      - l'occlusion ambiante 3D réelle (`mr.r = AO`),
      - l'usure d'arêtes géométrique (`compute_edge_wear`),
      - l'extraction de micro-relief haute fréquence -> normal map Sobel + rugosité.
    """
    S = int(spec.get("texture_size", 1024))
    lbl_in = labels if labels is not None else _assign_z_regions(mesh, spec)
    has_uv = (getattr(mesh.visual, "uv", None) is not None
              and len(mesh.visual.uv) == len(mesh.vertices))
    if has_uv:
        uv = np.asarray(mesh.visual.uv, dtype=np.float64)
        labels = lbl_in
    else:
        mesh, labels, uv = pbr.unwrap(mesh, lbl_in)

    nrm_v = np.asarray(mesh.vertex_normals, dtype=np.float64)
    wear_v = pbr.compute_edge_wear(mesh)
    ao_v = pbr.compute_ambient_occlusion(mesh)

    # Normalise les coordonnées 3D sur la boîte englobante pour un `scale` invariant
    vmin = mesh.vertices.min(0)
    diag = max(float(np.linalg.norm(mesh.vertices.max(0) - vmin)), 1e-6)

    regions = spec.get("regions", [])
    tiles = [_load_tile(r["tile"]) for r in regions]
    # Normalise la luminance moyenne de chaque tuile IA pour permettre un `tint` exact
    tile_means = [np.clip(t.mean(axis=(0, 1)), 0.08, None) for t in tiles]

    albedo = np.zeros((S, S, 3), dtype=np.float64)
    ao_t = np.ones((S, S), dtype=np.float64)
    rough_t = np.full((S, S), 0.5, dtype=np.float64)
    metal_t = np.zeros((S, S), dtype=np.float64)
    height_t = np.zeros((S, S), dtype=np.float64)
    filled = np.zeros((S, S), dtype=bool)

    faces = mesh.faces
    tri_uv = np.empty_like(uv[faces])
    tri_uv[..., 0] = uv[faces, 0] * S
    tri_uv[..., 1] = (1.0 - uv[faces, 1]) * S

    zmin, zmax = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
    zspan = max(zmax - zmin, 1e-6)

    rast = pbr.rasterize_uv_triangles(tri_uv, S)
    if rast is not None:
        fi, xs, ys, w0, w1, w2 = rast
        ia, ib, ic = faces[fi, 0], faces[fi, 1], faces[fi, 2]
        pos = w0[:, None] * mesh.vertices[ia] + w1[:, None] * mesh.vertices[ib] + w2[:, None] * mesh.vertices[ic]
        nrm = w0[:, None] * nrm_v[ia] + w1[:, None] * nrm_v[ib] + w2[:, None] * nrm_v[ic]
        nrm /= np.clip(np.linalg.norm(nrm, axis=-1, keepdims=True), 1e-9, None)
        w = np.stack([w0, w1, w2], 1)
        dom = labels[faces[fi, w.argmax(1)]]
        wear = w0 * wear_v[ia] + w1 * wear_v[ib] + w2 * wear_v[ic]
        ao = w0 * ao_v[ia] + w1 * ao_v[ib] + w2 * ao_v[ic]

        p_unit = (pos - vmin) / diag
        col_px = np.zeros((len(xs), 3), dtype=np.float64)
        rough_px = np.zeros(len(xs), dtype=np.float64)
        metal_px = np.zeros(len(xs), dtype=np.float64)
        hgt_px = np.zeros(len(xs), dtype=np.float64)

        for idx, reg in enumerate(regions):
            m = dom == idx
            if not m.any():
                continue
            sc = float(reg.get("scale", 2.2))
            samp = _triplanar_sample_tile(tiles[idx], p_unit[m], nrm[m], scale=sc)
            if reg.get("tint"):
                tint = pbr._hex2rgb(reg["tint"])
                detail = samp / tile_means[idx][None, :]
                c = np.clip(tint[None, :] * (0.30 + 0.70 * detail), 0.0, 1.0)
            else:
                c = samp
            lum_local = samp @ np.array([0.299, 0.587, 0.114])
            lum_centered = lum_local - float(tile_means[idx].mean())
            r_base = float(reg.get("roughness", 0.45))
            r_contrast = float(reg.get("roughness_contrast", -0.35))
            r_val = np.clip(r_base + r_contrast * lum_centered, 0.04, 1.0)
            m_val = np.full(m.sum(), float(reg.get("metallic", 0.0)), dtype=np.float64)

            ep = float(reg.get("edge_polish", 0.0))
            if ep > 0.0:
                w_m = np.clip((wear[m] - 0.18) * 1.5 * ep, 0.0, 1.0)
                edge_col = pbr._hex2rgb(reg.get("edge_color", "#d8dde4"))
                c = c * (1.0 - w_m[:, None]) + edge_col[None, :] * w_m[:, None]
                r_val = np.clip(r_val * (1.0 - 0.65 * w_m), 0.04, 1.0)
                m_val = np.clip(m_val + 0.75 * w_m, 0.0, 1.0)

            col_px[m] = c
            rough_px[m] = r_val
            metal_px[m] = m_val
            hgt_px[m] = lum_local

        for ov in spec.get("ai_overlays", []):
            ov_tile = _load_tile(ov["tile"])
            sc = float(ov.get("scale", 2.6))
            samp = _triplanar_sample_tile(ov_tile, p_unit, nrm, scale=sc)
            znorm = (pos[:, 2] - zmin) / zspan
            amt = float(ov.get("amount", 0.65))
            mode = ov.get("mode", "cavity")
            lum_o = samp @ np.array([0.299, 0.587, 0.114])
            if mode == "cavity":
                mask = np.clip(((1.0 - ao) * 1.45 + (1.0 - wear) * 0.35 - 0.28)
                               * (0.55 + lum_o) * amt * 1.8, 0.0, 1.0)
            elif mode == "low_mud":
                h_max = float(ov.get("height", 0.35))
                low = np.clip(1.0 - znorm / max(h_max, 1e-3), 0.0, 1.0) ** 1.4
                mask = np.clip(low * (0.45 + lum_o) * amt * 1.5, 0.0, 1.0)
            else:
                mask = np.clip((lum_o - 0.45) * 2.5 * amt, 0.0, 1.0)
            if "regions" in ov:
                allow = np.isin(dom, [regions.index(r) for r in regions
                                      if r.get("name") in ov["regions"]])
                mask *= allow
            col_px = col_px * (1.0 - mask[:, None]) + samp * mask[:, None]
            rough_px = np.clip(rough_px * (1.0 - mask) + float(ov.get("roughness", 0.90)) * mask, 0.04, 1.0)
            metal_px = np.clip(metal_px * (1.0 - mask) + float(ov.get("metallic", 0.05)) * mask, 0.0, 1.0)
            hgt_px = hgt_px * (1.0 - 0.5 * mask) + lum_o * 0.5 * mask

        albedo[ys, xs] = col_px
        ao_t[ys, xs] = ao
        rough_t[ys, xs] = rough_px
        metal_t[ys, xs] = metal_px
        height_t[ys, xs] = hgt_px
        filled[ys, xs] = True

    if (~filled).any() and filled.any():
        ind = ndimage.distance_transform_edt(~filled, return_distances=False, return_indices=True)
        albedo = albedo[ind[0], ind[1]]
        ao_t = ao_t[ind[0], ind[1]]
        rough_t = rough_t[ind[0], ind[1]]
        metal_t = metal_t[ind[0], ind[1]]
        height_t = height_t[ind[0], ind[1]]

    albedo8 = (np.clip(albedo, 0.0, 1.0) * 255).astype(np.uint8)
    gx = ndimage.sobel(height_t, 1) / 8.0
    gy = ndimage.sobel(height_t, 0) / 8.0
    k = float(spec.get("normal_strength", 2.6))
    nx, ny = -gx * k, -gy * k
    nz = np.ones_like(nx)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    normal8 = ((np.stack([nx / ln, ny / ln, nz / ln], -1) * 0.5 + 0.5) * 255).astype(np.uint8)
    mr8 = np.stack([np.clip(ao_t, 0.0, 1.0) * 255, rough_t * 255, metal_t * 255],
                   -1).astype(np.uint8)

    albedo_img = Image.fromarray(albedo8)
    mr_img = Image.fromarray(mr8)
    normal_img = Image.fromarray(normal8)
    pbr.attach_visual(mesh, uv, albedo_img, mr_img, normal_img,
                      name=spec.get("name", "ai_pbr_datacenter"))
    return mesh, {
        "albedo": albedo_img,
        "mr": mr_img,
        "normal": normal_img,
        "uv_coverage": float(filled.mean()),
        "ao_min": float(ao_v.min()),
        "ao_mean": float(ao_v.mean()),
    }


def bake_multiview_to_mesh(mesh: trimesh.Trimesh, cam_manifest: dict,
                           view_images: dict[str, str],
                           texture_size: int = 1024,
                           delight_strength: float = 0.55) -> tuple[trimesh.Trimesh, dict]:
    """Reprojette `N` rendus photo GPU (`view_images = {view_name: png_path}`)
    dans l'atlas UV `xatlas` du `.glb` avec test d'occlusion z-buffer exact par vue,
    pondération `cos^4(theta)` et division d'éclairage doux."""
    S = int(texture_size)
    if getattr(mesh.visual, "uv", None) is None or len(mesh.visual.uv) != len(mesh.vertices):
        mesh, _, uv = pbr.unwrap(mesh, np.zeros(len(mesh.vertices), dtype=np.int64))
    else:
        uv = np.asarray(mesh.visual.uv, dtype=np.float64)

    ao_v = pbr.compute_ambient_occlusion(mesh)
    nrm_v = np.asarray(mesh.vertex_normals, dtype=np.float64)
    faces = mesh.faces
    fn = np.asarray(mesh.face_normals, dtype=np.float64)

    #Pré-calcule le z-buffer de visibilité pour chaque vue fournie
    view_entries = []
    for vname, img_path in view_images.items():
        vinfo = cam_manifest["views"][vname]
        im = np.asarray(Image.open(img_path).convert("RGB"), dtype=np.float64) / 255.0
        H, W, _ = im.shape
        PV = np.asarray(vinfo["PV"], dtype=np.float64)
        V = np.asarray(vinfo["V"], dtype=np.float64)
        eye = np.asarray(vinfo["eye"], dtype=np.float64)
        # Rendu studio de référence à la même résolution pour estimer l'irradiance
        ref_im = np.asarray(Image.open(vinfo["studio"]).convert("RGB").resize((W, H), Image.BILINEAR),
                            dtype=np.float64) / 255.0

        vw = np.hstack([mesh.vertices, np.ones((len(mesh.vertices), 1))])
        clip = (PV @ vw.T).T
        wc = clip[:, 3]
        ok = wc > 1e-6
        ndc = clip[:, :3] / np.clip(wc[:, None], 1e-9, None)
        px = (ndc[:, 0] * 0.5 + 0.5) * W
        py = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * H
        zbuf = np.full((H, W), np.inf)
        renderer._rasterize_part(px, py, wc.copy(), ok, faces, W, H, zbuf, update_z=True)
        view_entries.append((im, ref_im, PV, eye, zbuf, W, H))

    acc_col = np.zeros((S, S, 3), dtype=np.float64)
    acc_w = np.zeros((S, S), dtype=np.float64)
    ao_t = np.ones((S, S), dtype=np.float64)
    filled = np.zeros((S, S), dtype=bool)

    tri_uv = np.empty_like(uv[faces])
    tri_uv[..., 0] = uv[faces, 0] * S
    tri_uv[..., 1] = (1.0 - uv[faces, 1]) * S

    rast = pbr.rasterize_uv_triangles(tri_uv, S)
    if rast is not None:
        fi, xs, ys, w0, w1, w2 = rast
        ia, ib, ic = faces[fi, 0], faces[fi, 1], faces[fi, 2]
        pos = w0[:, None] * mesh.vertices[ia] + w1[:, None] * mesh.vertices[ib] + w2[:, None] * mesh.vertices[ic]
        nrm = w0[:, None] * nrm_v[ia] + w1[:, None] * nrm_v[ib] + w2[:, None] * nrm_v[ic]
        nrm /= np.clip(np.linalg.norm(nrm, axis=-1, keepdims=True), 1e-9, None)
        ao_t[ys, xs] = w0 * ao_v[ia] + w1 * ao_v[ib] + w2 * ao_v[ic]
        filled[ys, xs] = True

        pw = np.hstack([pos, np.ones((len(pos), 1))])
        for im, ref_im, PV, eye, zbuf, W, H in view_entries:
            clip = (PV @ pw.T).T
            wc = clip[:, 3]
            ndc = clip[:, :3] / np.clip(wc[:, None], 1e-9, None)
            fx = (ndc[:, 0] * 0.5 + 0.5) * W
            fy = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * H
            ix = np.clip(np.round(fx - 0.5).astype(np.int64), 0, W - 1)
            iy = np.clip(np.round(fy - 0.5).astype(np.int64), 0, H - 1)
            in_frustum = (wc > 1e-6) & (fx >= 1) & (fx < W - 1) & (fy >= 1) & (fy < H - 1)
            vis = in_frustum & (wc <= zbuf[iy, ix] * 1.015 + 1e-3)
            vdir = eye[None, :] - pos
            vdir /= np.clip(np.linalg.norm(vdir, axis=-1, keepdims=True), 1e-9, None)
            cos_t = np.clip((nrm * vdir).sum(-1), 0.0, 1.0)
            w_view = np.where(vis, (cos_t ** 4) + 1e-4, 0.0)
            if not np.any(w_view > 0):
                continue
            c_raw = im[iy, ix]
            lum_ref = np.clip(ref_im[iy, ix].mean(-1, keepdims=True), 0.18, 1.4)
            c_delit = np.clip(c_raw / (lum_ref ** delight_strength) * (0.55 ** delight_strength), 0.0, 1.0)
            acc_col[ys, xs] += c_delit * w_view[:, None]
            acc_w[ys, xs] += w_view

    valid = acc_w > 1e-6
    albedo = np.zeros_like(acc_col)
    albedo[valid] = acc_col[valid] / acc_w[valid, None]
    if (~valid).any() and valid.any():
        ind = ndimage.distance_transform_edt(~valid, return_distances=False, return_indices=True)
        albedo = albedo[ind[0], ind[1]]
    if (~filled).any() and filled.any():
        ind = ndimage.distance_transform_edt(~filled, return_distances=False, return_indices=True)
        ao_t = ao_t[ind[0], ind[1]]

    lum = albedo @ np.array([0.299, 0.587, 0.114])
    gx = ndimage.sobel(lum, 1) / 8.0
    gy = ndimage.sobel(lum, 0) / 8.0
    nx, ny = -gx * 2.2, -gy * 2.2
    nz = np.ones_like(nx)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    normal_img = Image.fromarray(((np.stack([nx / ln, ny / ln, nz / ln], -1) * 0.5 + 0.5) * 255).astype(np.uint8))
    rough_t = np.clip(0.68 - 0.35 * (lum - lum.mean()), 0.10, 0.95)
    metal_t = np.full_like(rough_t, 0.25)
    mr_img = Image.fromarray(np.stack([ao_t * 255, rough_t * 255, metal_t * 255], -1).astype(np.uint8))
    albedo_img = Image.fromarray((np.clip(albedo, 0.0, 1.0) * 255).astype(np.uint8))
    pbr.attach_visual(mesh, uv, albedo_img, mr_img, normal_img, name="ai_multiview_baked")
    return mesh, {
        "albedo": albedo_img,
        "mr": mr_img,
        "normal": normal_img,
        "projected_coverage": float(valid[filled].mean()) if filled.any() else 0.0,
    }


def render_orthographic_paint_guides(
    scene_or_mesh,
    out_dir: str,
    size: int = 1024,
    pad: float = 0.075,
) -> dict:
    """Rend 3 guides orthographiques calibrés au millimètre (`front` `-Y`, `side` `+X`, `top` `+Z`)
    par Z-buffer analytique + éclairage studio diffus d'AO douce, prêts à être peints par
    le GPU Datacenter (`generate_image(..., images=[guide])`) puis reprojetés sans décalage !"""
    os.makedirs(out_dir, exist_ok=True)
    mesh = _single_mesh_from_scene(scene_or_mesh)
    bmin, bmax = mesh.bounds
    center = 0.5 * (bmin + bmax)
    span = float(np.max(bmax - bmin)) * (1.0 + 2.0 * float(pad))
    half = max(span * 0.5, 1e-5)

    ao_v = pbr.compute_ambient_occlusion(mesh).astype(np.float32)
    curv_v = pbr.compute_edge_wear(mesh).astype(np.float32)
    v_col = getattr(mesh.visual, "vertex_colors", None)
    if v_col is not None and len(v_col) == len(mesh.vertices):
        base_v = np.asarray(v_col[:, :3], dtype=np.float32) / 255.0
    else:
        base_v = np.full((len(mesh.vertices), 3), 0.55, dtype=np.float32)

    S = int(size)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    verts = np.asarray(mesh.vertices, dtype=np.float32) - center[None, :]
    vnorms = np.asarray(mesh.vertex_normals, dtype=np.float32)

    # Définition exacte des axes `(right, up, towards_cam)` pour `front`, `side`, `top`
    axes_spec = {
        "front": ([1, 0, 0], [0, 0, 1], [0, -1, 0]),
        "side":  ([0, 1, 0], [0, 0, 1], [1,  0, 0]),
        "top":   ([1, 0, 0], [0, 1, 0], [0,  0, 1]),
    }
    out_paths = {}
    for vname, (rx, uy, dz) in axes_spec.items():
        R_ax = np.asarray(rx, dtype=np.float32)
        U_ax = np.asarray(uy, dtype=np.float32)
        D_ax = np.asarray(dz, dtype=np.float32)
        px = ((verts @ R_ax) / half * 0.5 + 0.5) * (S - 1)
        py = (0.5 - (verts @ U_ax) / half * 0.5) * (S - 1)
        pz = verts @ D_ax  # plus grand = plus proche de la caméra !

        zbuf = np.full((S, S), -1e9, dtype=np.float32)
        img = np.full((S, S, 3), 0.94, dtype=np.float32)

        fn = np.cross(verts[faces[:, 1]] - verts[faces[:, 0]], verts[faces[:, 2]] - verts[faces[:, 0]])
        vis_f = np.flatnonzero((fn @ D_ax) > -1e-9)
        if len(vis_f):
            tri_2d = np.empty((len(vis_f), 3, 2), dtype=np.float64)
            tri_2d[..., 0] = px[faces[vis_f]]
            tri_2d[..., 1] = py[faces[vis_f]]
            rast = pbr.rasterize_uv_triangles(tri_2d, S)
            if rast is not None:
                fh_i, xs_i, ys_i, w0_i, w1_i, w2_i = rast
                orig_f = vis_f[fh_i]
                va_i, vb_i, vc_i = faces[orig_f, 0], faces[orig_f, 1], faces[orig_f, 2]
                w0f, w1f, w2f = w0_i.astype(np.float32), w1_i.astype(np.float32), w2_i.astype(np.float32)
                zz = w0f * pz[va_i] + w1f * pz[vb_i] + w2f * pz[vc_i]
                order = np.argsort(zz, kind="mergesort")  # peintre Arrière -> Avant exact !
                xs_s, ys_s, o_s = xs_i[order], ys_i[order], order
                va_s, vb_s, vc_s = va_i[o_s], vb_i[o_s], vc_i[o_s]
                w0s, w1s, w2s = w0f[o_s], w1f[o_s], w2f[o_s]
                zbuf[ys_s, xs_s] = zz[o_s]
                n_interp = w0s[:, None] * vnorms[va_s] + w1s[:, None] * vnorms[vb_s] + w2s[:, None] * vnorms[vc_s]
                n_interp /= np.linalg.norm(n_interp, axis=-1, keepdims=True) + 1e-9
                c_interp = w0s[:, None] * base_v[va_s] + w1s[:, None] * base_v[vb_s] + w2s[:, None] * base_v[vc_s]
                ao_i = w0s * ao_v[va_s] + w1s * ao_v[vb_s] + w2s * ao_v[vc_s]
                cr_i = w0s * curv_v[va_s] + w1s * curv_v[vb_s] + w2s * curv_v[vc_s]
                hemi = 0.62 + 0.38 * np.clip(n_interp @ D_ax, 0.0, 1.0)
                img[ys_s, xs_s] = np.clip((c_interp * hemi[:, None] + 0.10 * cr_i[:, None]) * ao_i[:, None], 0.0, 1.0)

        out_p = os.path.join(out_dir, f"ortho_{vname}.png")
        Image.fromarray((img * 255.0).round().astype(np.uint8), mode="RGB").save(out_p, compress_level=1)
        out_paths[vname] = out_p

    meta = {"center": center.tolist(), "half_extent": half, "size": S, "guides": out_paths}
    with open(os.path.join(out_dir, "ortho_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    return meta


def _align_and_clean_ai_ortho(vpath: str, vname: str, S: int) -> tuple[np.ndarray, np.ndarray]:
    """Aligne au sous-pixel près une vue peinte sur GPU Datacenter (`ai_front.png`, `ai_side.png`)
    sur la silhouette exacte de son guide géométrique `ortho_<vname>.png` s'il est présent dans le
    même dossier, supprime 100 % du halo clair de fond par érosion + extension EDT interne, et
    obscurcit les trous traversants internes (bouche ouverte / pupilles) pour zéro bavure grise."""
    import delight as dl

    raw_im = Image.open(vpath).convert("RGB").resize((S, S), Image.Resampling.LANCZOS)
    arr_raw = np.asarray(raw_im, dtype=np.float32) / 255.0

    b = max(4, S // 32)
    bg = np.median(np.concatenate([
        arr_raw[:b, :, :].reshape(-1, 3),
        arr_raw[-b:, :, :].reshape(-1, 3),
        arr_raw[:, :b, :].reshape(-1, 3),
        arr_raw[:, -b:, :].reshape(-1, 3),
    ], axis=0), axis=0)
    dist_bg = np.linalg.norm(arr_raw - bg[None, None, :], axis=2)
    sat = arr_raw.max(axis=2) - arr_raw.min(axis=2)
    fg_raw = (dist_bg > 0.075) | (sat > 0.055)
    fg_closed = ndimage.binary_closing(fg_raw, iterations=2)
    fg_outer = ndimage.binary_fill_holes(fg_closed)
    lbl, n_c = ndimage.label(fg_outer)
    if n_c > 1:
        sizes = ndimage.sum(fg_outer, lbl, range(1, n_c + 1))
        fg_outer = lbl == (int(np.argmax(sizes)) + 1)

    delit_im, _ = dl.delight_image_2d(raw_im, strength=0.48)
    rgb = np.asarray(delit_im, dtype=np.float32) / 255.0
    rgb = np.clip(rgb, 0.0, 0.88)
    rgb[..., 1] = np.where((rgb[..., 0] > 0.58) & (rgb[..., 1] > 0.22 * rgb[..., 0]) & (rgb[..., 2] < 0.16),
                           rgb[..., 0] * 0.16, rgb[..., 1])
    inner_holes = fg_outer & (~fg_raw)
    if inner_holes.any():
        rgb[inner_holes] = np.array([0.030, 0.022, 0.024], dtype=np.float32)

    # Érode de 4 px puis prolonge par EDT vers l'extérieur -> 0.0 % de frange claire sur les bords !
    inner_valid = ndimage.binary_erosion(fg_outer, iterations=4)
    if not inner_valid.any():
        inner_valid = fg_outer
    if inner_valid.any():
        _, nn = ndimage.distance_transform_edt(~inner_valid, return_indices=True)
        rgb = rgb[nn[0], nn[1]]

    # Recalage affine automatique boîte-à-boîte sur `ortho_<vname>.png` s'il existe à côté !
    guide_p = os.path.join(os.path.dirname(str(vpath)), f"ortho_{vname}.png")
    if os.path.isfile(guide_p) and fg_outer.sum() > 200:
        g_arr = np.asarray(Image.open(guide_p).convert("RGB").resize((S, S), Image.Resampling.BILINEAR),
                           dtype=np.float32) / 255.0
        g_bg = np.median(g_arr[:b, :, :].reshape(-1, 3), axis=0)
        g_fg = ndimage.binary_fill_holes(np.linalg.norm(g_arr - g_bg[None, None, :], axis=2) > 0.055)
        if g_fg.sum() > 200:
            ays, axs = np.nonzero(fg_outer)
            gys, gxs = np.nonzero(g_fg)
            ay0, ay1, ax0, ax1 = float(ays.min()), float(ays.max()), float(axs.min()), float(axs.max())
            gy0, gy1, gx0, gx1 = float(gys.min()), float(gys.max()), float(gxs.min()), float(gxs.max())
            grid_y = (np.arange(S, dtype=np.float32) - gy0) / max(gy1 - gy0, 1.0) * max(ay1 - ay0, 1.0) + ay0
            grid_x = (np.arange(S, dtype=np.float32) - gx0) / max(gx1 - gx0, 1.0) * max(ax1 - ax0, 1.0) + ax0
            gx_c = np.clip(grid_x, 0.0, S - 1.001)
            gy_c = np.clip(grid_y, 0.0, S - 1.001)
            x0i = gx_c.astype(np.int32)
            y0i = gy_c.astype(np.int32)
            tx = (gx_c - x0i)[None, :, None]
            ty = (gy_c - y0i)[:, None, None]
            c00 = rgb[np.ix_(y0i, x0i)]
            c10 = rgb[np.ix_(y0i, np.minimum(x0i + 1, S - 1))]
            c01 = rgb[np.ix_(np.minimum(y0i + 1, S - 1), x0i)]
            c11 = rgb[np.ix_(np.minimum(y0i + 1, S - 1), np.minimum(x0i + 1, S - 1))]
            rgb = (c00 * (1.0 - tx) + c10 * tx) * (1.0 - ty) + (c01 * (1.0 - tx) + c11 * tx) * ty

    lum_a = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    hp_a = (lum_a - ndimage.gaussian_filter(lum_a, sigma=3.0)).astype(np.float32)
    return rgb.astype(np.float32), hp_a


def sample_orthographic_ai_views_zbuffer(
    high_mesh: trimesh.Trimesh,
    sample_pos: np.ndarray,
    sample_nrm: np.ndarray,
    ai_views: dict[str, str],
    pad: float = 0.075,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Projette des vues orthographiques peintes par le GPU Datacenter (`front`, `side`, `top`)
    sur les points 3D `sample_pos` de `high_mesh` AVEC **vrai test d'occultation Z-buffer** :
      - Zéro bavure sur les faces cachées ou à l'arrière creux des masques !
      - Recalage automatique de silhouette + anti-halo EDT sur `1024×1024` !
      - Enrichissement triplanaire haute fréquence par tuiles GPU (`tile_*.png`) si présentes !
      - Retourne `(ai_rgb, ai_detail_height, coverage_weight)` alignés sur `sample_pos`.
    """
    bmin, bmax = high_mesh.bounds
    center = 0.5 * (bmin + bmax)
    span = float(np.max(bmax - bmin)) * (1.0 + 2.0 * float(pad))
    half = max(span * 0.5, 1e-5)

    ai_dir = None
    for vp in ai_views.values():
        if vp and os.path.exists(vp):
            ai_dir = os.path.dirname(str(vp))
            meta_p = os.path.join(ai_dir, "ortho_meta.json")
            if os.path.exists(meta_p):
                with open(meta_p, encoding="utf-8") as fh:
                    om = json.load(fh)
                center = np.asarray(om["center"], dtype=np.float32)
                half = float(om["half_extent"])
                break

    S = 1024
    faces = np.asarray(high_mesh.faces, dtype=np.int64)
    verts = np.asarray(high_mesh.vertices, dtype=np.float32) - center[None, :]
    pts = np.asarray(sample_pos, dtype=np.float32) - center[None, :]
    nrm = np.asarray(sample_nrm, dtype=np.float32)

    # Ne projette JAMAIS `front` sur le dos `+Y` si `back` n'est pas fourni (évite un visage fantôme au dos !)
    cardinal = []
    if "front" in ai_views and os.path.exists(ai_views["front"]):
        cardinal.append((ai_views["front"], "front", [1, 0, 0], [0, 0, 1], [0, -1, 0], False))
    if "back" in ai_views and os.path.exists(ai_views["back"]):
        cardinal.append((ai_views["back"], "back", [-1, 0, 0], [0, 0, 1], [0, 1, 0], False))
    if "side" in ai_views and os.path.exists(ai_views["side"]):
        cardinal.append((ai_views["side"], "side", [0, 1, 0], [0, 0, 1], [1, 0, 0], False))
        cardinal.append((ai_views.get("left", ai_views["side"]), "side", [0, -1, 0], [0, 0, 1], [-1, 0, 0], "left" not in ai_views))
    if "top" in ai_views and os.path.exists(ai_views["top"]):
        cardinal.append((ai_views["top"], "top", [1, 0, 0], [0, 1, 0], [0, 0, 1], False))

    acc_rgb = np.zeros((len(pts), 3), dtype=np.float32)
    acc_hgt = np.zeros((len(pts),), dtype=np.float32)
    acc_w = np.zeros((len(pts),), dtype=np.float32)

    if not hasattr(sample_orthographic_ai_views_zbuffer, "_img_cache"):
        sample_orthographic_ai_views_zbuffer._img_cache = {}
    tex_cache = sample_orthographic_ai_views_zbuffer._img_cache

    fn = np.cross(verts[faces[:, 1]] - verts[faces[:, 0]], verts[faces[:, 2]] - verts[faces[:, 0]])
    for vpath, vname, rx, uy, dz, mirrored in cardinal:
        mtime_key = (vpath, vname, os.path.getmtime(vpath), S)
        if mtime_key not in tex_cache:
            tex_cache[mtime_key] = _align_and_clean_ai_ortho(vpath, vname, S)
        rgb_a, hp_a = tex_cache[mtime_key]
        if mirrored:
            rgb_a = rgb_a[:, ::-1, :]
            hp_a = hp_a[:, ::-1]

        R_ax = np.asarray(rx, dtype=np.float32)
        U_ax = np.asarray(uy, dtype=np.float32)
        D_ax = np.asarray(dz, dtype=np.float32)

        # Z-buffer 100 % vectorisé NumPy (`np.maximum.at`, zéro boucle Python par triangle !)
        px = ((verts @ R_ax) / half * 0.5 + 0.5) * (S - 1)
        py = (0.5 - (verts @ U_ax) / half * 0.5) * (S - 1)
        pz = verts @ D_ax
        zbuf = np.full((S, S), -1e9, dtype=np.float32)
        vis_f = np.flatnonzero((fn @ D_ax) > -1e-9)
        if len(vis_f):
            tri_2d = np.empty((len(vis_f), 3, 2), dtype=np.float64)
            tri_2d[..., 0] = px[faces[vis_f]]
            tri_2d[..., 1] = py[faces[vis_f]]
            rast = pbr.rasterize_uv_triangles(tri_2d, S)
            if rast is not None:
                fh_i, xs_i, ys_i, w0_i, w1_i, w2_i = rast
                orig_f = vis_f[fh_i]
                zz = (w0_i.astype(np.float32) * pz[faces[orig_f, 0]]
                      + w1_i.astype(np.float32) * pz[faces[orig_f, 1]]
                      + w2_i.astype(np.float32) * pz[faces[orig_f, 2]])
                np.maximum.at(zbuf, (ys_i, xs_i), zz)

        # Dilate légèrement le Z-buffer max local 3x3 pour éviter l'acné aux rasances
        zmax_local = ndimage.maximum_filter(zbuf, size=3)
        sx_p = np.clip(((pts @ R_ax) / half * 0.5 + 0.5) * (S - 1), 0, S - 1)
        sy_p = np.clip((0.5 - (pts @ U_ax) / half * 0.5) * (S - 1), 0, S - 1)
        sz_p = pts @ D_ax
        ix, iy = sx_p.round().astype(np.int32), sy_p.round().astype(np.int32)

        facing = np.clip(nrm @ D_ax, 0.0, 1.0)
        unoccluded = sz_p >= (zmax_local[iy, ix] - half * 0.035)
        w = (facing ** 5) * unoccluded.astype(np.float32)
        hit_m = w > 1e-4
        if not hit_m.any():
            continue
        acc_rgb[hit_m] += rgb_a[iy[hit_m], ix[hit_m]] * w[hit_m, None]
        acc_hgt[hit_m] += hp_a[iy[hit_m], ix[hit_m]] * w[hit_m]
        acc_w[hit_m] += w[hit_m]

    cov = np.clip(acc_w / (acc_w + 0.05), 0.0, 1.0)
    out_rgb = np.zeros_like(acc_rgb)
    out_hgt = np.zeros_like(acc_hgt)
    ok = acc_w > 1e-5
    out_rgb[ok] = acc_rgb[ok] / acc_w[ok, None]
    out_hgt[ok] = acc_hgt[ok] / acc_w[ok]
    return out_rgb, out_hgt, cov


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_prep = sub.add_parser("prepare", help="Exporte guides studio/depth/normal/mask + cameras.json")
    p_prep.add_argument("glb")
    p_prep.add_argument("-o", "--outdir", required=True)
    p_prep.add_argument("--size", type=int, default=1024)

    p_tiles = sub.add_parser("bake-tiles", help="Bake triplanaire de tuiles IA dans l'atlas UV d'un .glb")
    p_tiles.add_argument("glb")
    p_tiles.add_argument("--spec", required=True, help="JSON décrivant les tuiles GPU par région")
    p_tiles.add_argument("-o", "--out", required=True, help="Chemin du .glb photoréaliste de sortie")

    p_mv = sub.add_parser("bake-views", help="Reprojette N vues GPU dans l'atlas UV d'un .glb")
    p_mv.add_argument("glb")
    p_mv.add_argument("--cameras", required=True, help="cameras.json produit par `prepare`")
    p_mv.add_argument("--view", action="append", required=True,
                      help="Paire nom=chemin.png, ex. hero=photo_hero.png")
    p_mv.add_argument("-o", "--out", required=True)
    p_mv.add_argument("--size", type=int, default=1024)

    args = ap.parse_args()
    if args.cmd == "prepare":
        info = prepare_guides(args.glb, args.outdir, size=args.size)
        print(json.dumps({"cameras_json": os.path.join(args.outdir, "cameras.json"),
                          "views": list(info["views"].keys())}, indent=2))
    elif args.cmd == "bake-tiles":
        mesh = _single_mesh_from_scene(trimesh.load(args.glb, force="scene"))
        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
        out_mesh, meta = bake_ai_tiles_to_mesh(mesh, spec)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        out_mesh.export(args.out)
        print(json.dumps({"out": args.out, "uv_coverage": meta["uv_coverage"],
                          "ao_mean": meta["ao_mean"]}, indent=2))
    elif args.cmd == "bake-views":
        mesh = _single_mesh_from_scene(trimesh.load(args.glb, force="scene"))
        with open(args.cameras, encoding="utf-8") as fh:
            cams = json.load(fh)
        vmap = dict(item.split("=", 1) for item in args.view)
        out_mesh, meta = bake_multiview_to_mesh(mesh, cams, vmap, texture_size=args.size)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        out_mesh.export(args.out)
        print(json.dumps({"out": args.out,
                          "projected_coverage": meta["projected_coverage"]}, indent=2))


if __name__ == "__main__":
    main()
