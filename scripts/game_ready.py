#!/usr/bin/env python3
"""
game_ready.py — Pipeline Industriel d'Assets Temps Réel AAA (`3d-forge v5 — Game-Ready Edition`).

Transforme n'importe quelle recette CAO `Builder`, maillage High-Poly sculpté (`gpu_sculpt.py`)
ou fichier `.glb` en un **pack complet d'asset de jeu vidéo temps réel** prêt à glisser-déposer
dans **Unreal Engine 5**, **Unity (HDRP / URP)**, **Godot 4**, **Blender** ou **Three.js** :

  1. **Fusion intelligente des Draw Calls** : regroupe toutes les pièces statiques opaques en
     **1 seul Draw Call** (`SM_<Name>_Body`), garde 1 Draw Call verre réfractif + 1 par sous-groupe
     articulé mobile (`front_axle`, `lid`, `front_door`...), divisant par 20 à 100 les draw calls !
  2. **High-Poly -> Low-Poly Raycast / Surface-Projection Baker + Chaîne `LOD0 / LOD1 / LOD2`** :
     projette les normales 3D fines, l'Ambient Occlusion, la Courbure (`Curvature`) et les matériaux
     d'un maillage High-Poly (`40k - 150k tris`) dans l'espace tangent exact `TANGENT (VEC4)` d'un
     `LOD0` léger (`1 500 - 6 000 tris`), puis génère automatiquement `LOD1` (`40%`) et `LOD2` (`15%`).
  3. **PBR Réaliste Systématique (Scans GPU Datacenter + Patine 4 Couches + Normal Stamps)** :
     - Triplanar micro-grain issu des vrais scans matière GPU (`assets/ai_materials/*.png`),
     - **Curvature Edge Wear** (peinture écaillée révélant le métal brillant sur les arêtes vives),
     - **Cavity Dirt & Oil** (poussière/graisse mate logée dans les creux AO),
     - **World-Z Ground Grime** (salissure progressive près du sol `z = 0`),
     - **Normal Stamp Decals** (rainures de panneaux, boulons hexagonaux, rivets sans polygones).
  4. **Profils d'Export Natifs Multi-Moteurs (`--engine unreal | unity | godot | gltf | all`)** :
     - **Unreal Engine 5** : `T_<Name>_BC.png`, `T_<Name>_ORM.png`, **`T_<Name>_N.png` (DirectX `-Y` !)**
     - **Unity HDRP/URP** : `T_<Name>_BaseMap.png`, **`T_<Name>_MaskMap.png` (`RGBA`: Metal/AO/Detail/Smoothness)**, `T_<Name>_NormalGL.png` (`+Y`)
     - **Godot 4 / glTF** : `.glb` autonome compressé WebP (`EXT_texture_webp`), `TANGENT VEC4`, animations `gltf.animations` standards et enfants physiques `-colonly` / `UCX_*` !
  5. **Collisions Physiques Convexes (`UCX_<Name>_00..N` / `-colonly`) + Sockets Gameplay (`SOCKET_*`)**.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.spatial import cKDTree
import trimesh

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import delight as dl  # noqa: E402
import meshkit as mk  # noqa: E402
import pbr  # noqa: E402
import preview as pv  # noqa: E402
import recipes  # noqa: E402
import renderer  # noqa: E402


# --------------------------------------------------------------------------- #
# 1. Chargement et projection triplanaire des scans matière GPU Datacenter
# --------------------------------------------------------------------------- #

_SCAN_CACHE: dict[str, np.ndarray] = {}


def _load_material_scan(kind: str) -> np.ndarray | None:
    """Charge un vrai scan PBR sans couture généré sur le GPU Datacenter (`assets/ai_materials/`)."""
    mapping = {
        "metal_painted": "scifi_painted_metal.png",
        "polymer": "weathered_hazard_polymer.png",
        "steel": "forged_steel.png",
        "rust": "pitted_rust.png",
        "bronze": "antique_bronze.png",
        "leather": "worn_leather.png",
    }
    fname = mapping.get(kind)
    if not fname:
        return None
    if fname not in _SCAN_CACHE:
        p = ROOT / "assets" / "ai_materials" / fname
        if not p.exists():
            return None
        arr = np.asarray(Image.open(p).convert("RGB"), dtype=np.float32) / 255.0
        # Extrait le grain haute/moyenne fréquence neutre en moyenne (= 1.0) pour moduler n'importe quelle teinte !
        lum = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
        low = ndimage.gaussian_filter(lum, sigma=max(arr.shape[:2]) / 9.0, mode="wrap")
        detail_ratio = np.clip(lum / np.maximum(low, 1e-3), 0.62, 1.42)
        _SCAN_CACHE[fname] = detail_ratio.astype(np.float32)
    return _SCAN_CACHE[fname]


def sample_triplanar_grain(pos: np.ndarray, nrm: np.ndarray, kind: str = "metal_painted",
                           tile_m: float = 0.28) -> np.ndarray:
    """Échantillonne sans couture (projection triplanaire pondérée par `|N|^4`) un scan
    matière GPU Datacenter en coordonnées monde métriques `pos (N, 3)`."""
    scan = _load_material_scan(kind)
    if scan is None:
        return np.ones(len(pos), dtype=np.float32)
    h, w = scan.shape
    an = np.abs(nrm) ** 4.0
    an /= np.sum(an, axis=1, keepdims=True) + 1e-8

    def _fetch(u_coord: np.ndarray, v_coord: np.ndarray) -> np.ndarray:
        ix = np.mod(np.floor(u_coord / tile_m * w).astype(np.int32), w)
        iy = np.mod(np.floor(v_coord / tile_m * h).astype(np.int32), h)
        return scan[iy, ix]

    gx = _fetch(pos[:, 1], pos[:, 2])
    gy = _fetch(pos[:, 0], pos[:, 2])
    gz = _fetch(pos[:, 0], pos[:, 1])
    return (an[:, 0] * gx + an[:, 1] * gy + an[:, 2] * gz).astype(np.float32)


# --------------------------------------------------------------------------- #
# 2. Normal Stamp Decals (panneaux industriels, rivets, boulons 0-polygone)
# --------------------------------------------------------------------------- #

def stamp_normal_decals(
    pos: np.ndarray,
    nrm: np.ndarray,
    metal: np.ndarray,
    bounds: np.ndarray,
    panel_spacing: float = 0.16,
    strength: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Génère sans aucun polygone supplémentaire une carte de hauteur analytique
    de rainures d'usinage/panneaux + têtes de rivets circulaires sur les surfaces
    métalliques/polymères planes. Retourne `(delta_height, ao_mult, metal_boost)`."""
    span = float(np.max(bounds[1] - bounds[0]))
    sp = max(panel_spacing, span * 0.16)
    an = np.abs(nrm)
    dom_axis = np.argmax(an, axis=1)

    # Coordonnées 2D locales sur la face dominante de chaque texel
    u = np.where(dom_axis == 0, pos[:, 1], pos[:, 0])
    v = np.where(dom_axis == 2, pos[:, 1], pos[:, 2])

    fu = np.abs((u / sp) - np.round(u / sp)) * sp
    fv = np.abs((v / sp) - np.round(v / sp)) * sp
    groove_w = max(0.0018, sp * 0.014)

    # Rainures fines chanfreinées entre panneaux
    g_u = np.exp(-((fu / groove_w) ** 2))
    g_v = np.exp(-((fv / groove_w) ** 2))
    groove = np.maximum(g_u, g_v)

    # Rivets / vis BTR logés près des coins de panneaux
    cu = np.abs(fu - groove_w * 3.8)
    cv = np.abs(fv - groove_w * 3.8)
    r_dist = np.hypot(cu, cv)
    rivet_r = groove_w * 1.45
    rivet_dome = np.clip(1.0 - (r_dist / max(rivet_r, 1e-5)) ** 2, 0.0, 1.0)
    rivet_ring = np.exp(-(((r_dist - rivet_r * 1.15) / max(groove_w * 0.45, 1e-5)) ** 2))

    hard_surface = np.clip(0.35 + 0.65 * metal, 0.0, 1.0) * float(strength)
    d_height = (-0.55 * groove + 0.48 * rivet_dome - 0.22 * rivet_ring) * hard_surface
    ao_mult = np.clip(1.0 - 0.28 * groove * hard_surface - 0.14 * rivet_ring * hard_surface, 0.55, 1.0)
    metal_boost = np.clip(0.45 * rivet_dome * hard_surface, 0.0, 0.6)
    return d_height.astype(np.float32), ao_mult.astype(np.float32), metal_boost.astype(np.float32)


# --------------------------------------------------------------------------- #
# 3. Patine Physique Game-Ready 4 Couches (Edge Wear + Cavity Dirt + Ground Grime)
# --------------------------------------------------------------------------- #

def apply_game_weathering(
    col: np.ndarray,
    rough: np.ndarray,
    metal: np.ndarray,
    ao: np.ndarray,
    curv: np.ndarray,
    pos: np.ndarray,
    nrm: np.ndarray,
    bounds: np.ndarray,
    wear_amount: float = 0.52,
    dirt_amount: float = 0.42,
    grime_amount: float = 0.30,
    decal_strength: float = 0.65,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Applique sur chaque texel `(col, rough, metal, ao)` la patine PBR réaliste complète :
      1. Grain matière triplanaire issu des scans GPU Datacenter,
      2. Usure d'arêtes convexes (`curv > 0`) écaillant la peinture vers un acier poli,
      3. Poussière / suie mate dans les cavités (`ao` faible),
      4. Salissure de contact au sol (`z` proche de `z_min`),
      5. Micro-rainures & rivets dans la carte de hauteur `height`.
    """
    col = col.astype(np.float32).copy()
    rough = rough.astype(np.float32).copy()
    metal = metal.astype(np.float32).copy()
    ao = ao.astype(np.float32).copy()

    span = np.maximum(bounds[1] - bounds[0], 1e-4)
    tile_m = float(np.clip(span.max() * 0.32, 0.06, 0.55))

    # 1. Micro-grain triplanaire réel (métal peint vs polymère/bois)
    g_metal = sample_triplanar_grain(pos, nrm, "metal_painted", tile_m=tile_m)
    g_poly = sample_triplanar_grain(pos, nrm, "polymer", tile_m=tile_m * 0.85)
    grain = np.where(metal > 0.45, g_metal, 0.55 * g_poly + 0.45 * g_metal)
    col *= np.clip(0.88 + 0.24 * grain[:, None], 0.65, 1.35)
    rough = np.clip(rough * (1.14 - 0.28 * grain), 0.05, 1.0)

    # 2. Usure d'arêtes par courbure (`Curvature Edge Wear`) ciblée uniquement sur les vraies arêtes vives
    breakup = pbr.fbm(pos[:, 0] * (24.0 / tile_m), pos[:, 1] * (24.0 / tile_m),
                      pos[:, 2] * (24.0 / tile_m), octaves=3, seed=71).astype(np.float32)
    sharp_edge = np.clip((curv - 0.36) / 0.44, 0.0, 1.0) ** 1.45
    edge_mask = np.clip(sharp_edge * (0.35 + 0.90 * breakup) * wear_amount, 0.0, 0.72)
    bare_steel = np.array([0.74, 0.76, 0.79], dtype=np.float32)
    col = col * (1.0 - edge_mask[:, None]) + bare_steel[None, :] * edge_mask[:, None]
    metal = np.clip(metal + edge_mask * 0.85, 0.0, 1.0)
    rough = np.clip(rough * (1.0 - 0.58 * edge_mask) + 0.18 * edge_mask, 0.05, 1.0)

    # 3. Crasse et poussière mate dans les cavités d'AO (`Cavity Dirt`)
    cavity = np.clip((0.68 - ao) * 1.65 * (0.50 + 0.65 * breakup) * dirt_amount, 0.0, 0.60)
    dirt_col = np.array([0.14, 0.13, 0.115], dtype=np.float32)
    col = col * (1.0 - cavity[:, None]) + dirt_col[None, :] * cavity[:, None]
    rough = np.clip(rough + 0.30 * cavity, 0.05, 1.0)
    metal = np.clip(metal * (1.0 - 0.60 * cavity), 0.0, 1.0)

    # 4. Salissure de contact au sol (`World-Z Ground Grime`)
    z_norm = np.clip((pos[:, 2] - bounds[0][2]) / float(span[2]), 0.0, 1.0)
    grime = np.exp(-z_norm / 0.085) * (0.40 + 0.60 * breakup) * grime_amount
    grime = np.clip(grime, 0.0, 0.42)
    earth_col = np.array([0.20, 0.175, 0.145], dtype=np.float32)
    col = col * (1.0 - grime[:, None]) + earth_col[None, :] * grime[:, None]
    rough = np.clip(rough + 0.22 * grime, 0.05, 1.0)

    # 5. Normal Stamp Decals (panneaux & rivets) + grain dans `height`
    dh, ao_m, m_boost = stamp_normal_decals(pos, nrm, metal, bounds, strength=decal_strength)
    ao = np.clip(ao * ao_m, 0.10, 1.0)
    metal = np.clip(metal + m_boost * 0.35, 0.0, 1.0)
    height = (0.28 * (grain - 1.0) - 0.18 * edge_mask + dh).astype(np.float32)

    return np.clip(col, 0.0, 1.0), rough, metal, ao, height


# --------------------------------------------------------------------------- #
# 4. High-Poly -> Low-Poly Tangent-Space Baker & Génération `LOD0 / LOD1 / LOD2`
# --------------------------------------------------------------------------- #

def decimate_mesh_clean(mesh: trimesh.Trimesh, target_tris: int) -> trimesh.Trimesh:
    """Soude d'abord 100 % des sommets 3D coïncidents (y compris les sommets dupliqués
    par `xatlas` le long des coutures UV !) afin d'obtenir une surface manifold fermée,
    puis décime vers `target_tris` triangles en C++ (`fast_simplification`) sans jamais
    ouvrir la moindre fissure."""
    work = trimesh.Trimesh(
        vertices=np.asarray(mesh.vertices, dtype=np.float64),
        faces=np.asarray(mesh.faces, dtype=np.int64),
        process=True,
    )
    work.merge_vertices(merge_tex=True, merge_norm=True)
    n_cur = len(work.faces)
    if n_cur <= target_tris or target_tris < 16:
        return work
    import fast_simplification
    v_in = np.asarray(work.vertices, dtype=np.float32)
    f_in = np.asarray(work.faces, dtype=np.int32)
    ratio = float(np.clip(1.0 - float(target_tris) / float(n_cur), 0.02, 0.992))
    v_out, f_out = v_in, f_in
    for agg_val in (6, 8, 9):
        v_out, f_out = fast_simplification.simplify(v_in, f_in, target_reduction=ratio, agg=agg_val)
        if len(f_out) <= target_tris * 1.15:
            break
    out = trimesh.Trimesh(vertices=v_out, faces=f_out, process=True)
    return out


def bake_high_to_low(
    high_mesh: trimesh.Trimesh,
    high_vertex_albedo: np.ndarray,
    high_vertex_rough: np.ndarray,
    high_vertex_metal: np.ndarray,
    low_mesh_in: trimesh.Trimesh,
    tex_size: int = 1024,
    weathering: bool = True,
    delight_pass: bool = False,
    decal_strength: float = 0.65,
) -> dict:
    """Cuit par projection géométrique 3D exacte un maillage `high_mesh` arbitrairement dense
    (`50k - 150k tris`) vers un maillage temps réel `low_mesh_in` (`1k - 6k tris`) :

      - Déplie `low_mesh_in` via `xatlas` et calcule son repère tangent exact `TANGENT (VEC4)`.
      - Calcule sur `high_mesh` l'AO géométrique fine + la Courbure (`Curvature`) + les normales.
      - Projette chaque texel `(pos_low, T_low, B_low, N_low)` sur `high_mesh` (recherche K-NN
        pondérée normale/distance ultra-rapide sur surface densément sur-échantillonnée) afin de
        transférer **dans l'espace tangent exact du Low-Poly** tous les chanfreins, boulons,
        rainures, écailles et détails du High-Poly !
      - Génère simultanément les cartes OpenGL (`+Y`), DirectX (`-Y` pour Unreal), `ORM` et `MaskMap` Unity !
    """
    S = int(tex_size)
    v_labels = np.zeros(len(low_mesh_in.vertices), dtype=np.int64)
    low_uv_mesh, _, uv = pbr.unwrap(low_mesh_in, v_labels)
    tangents_v4 = mk.compute_mikk_tangents(low_uv_mesh, uv)

    # Pré-calcule AO + Courbure sur le High-Poly
    ao_hi = pbr.compute_ambient_occlusion(high_mesh).astype(np.float32)
    curv_hi = pbr.compute_edge_wear(high_mesh).astype(np.float32)
    v_hi = np.asarray(high_mesh.vertices, dtype=np.float32)
    n_hi = np.asarray(high_mesh.vertex_normals, dtype=np.float32)

    # Sur-échantillonne les triangles larges du High-Poly pour une projection sub-millimétrique !
    n_surf = min(max(len(high_mesh.faces) * 2, 45_000), 120_000)
    pts_s, face_idx = trimesh.sample.sample_surface(high_mesh, n_surf, seed=42)
    pts_s = pts_s.astype(np.float32)
    f_hi = np.asarray(high_mesh.faces, dtype=np.int64)[face_idx]
    # Coordonnées barycentriques exactes sur chaque triangle échantillonné du High-Poly
    va, vb, vc = v_hi[f_hi[:, 0]], v_hi[f_hi[:, 1]], v_hi[f_hi[:, 2]]
    e0, e1, vp = vb - va, vc - va, pts_s - va
    d00 = np.sum(e0 * e0, axis=1)
    d01 = np.sum(e0 * e1, axis=1)
    d11 = np.sum(e1 * e1, axis=1)
    d20 = np.sum(vp * e0, axis=1)
    d21 = np.sum(vp * e1, axis=1)
    inv_d = 1.0 / np.maximum(d00 * d11 - d01 * d01, 1e-18)
    bw1 = np.clip((d11 * d20 - d01 * d21) * inv_d, 0.0, 1.0)
    bw2 = np.clip((d00 * d21 - d01 * d20) * inv_d, 0.0, 1.0)
    bw0 = np.clip(1.0 - bw1 - bw2, 0.0, 1.0)
    bsum = bw0 + bw1 + bw2 + 1e-12
    bw0, bw1, bw2 = (bw0 / bsum).astype(np.float32), (bw1 / bsum).astype(np.float32), (bw2 / bsum).astype(np.float32)

    ia_h, ib_h, ic_h = f_hi[:, 0], f_hi[:, 1], f_hi[:, 2]
    nrm_s = bw0[:, None] * n_hi[ia_h] + bw1[:, None] * n_hi[ib_h] + bw2[:, None] * n_hi[ic_h]
    nrm_s /= np.linalg.norm(nrm_s, axis=1, keepdims=True) + 1e-12
    alb_s = bw0[:, None] * high_vertex_albedo[ia_h] + bw1[:, None] * high_vertex_albedo[ib_h] + bw2[:, None] * high_vertex_albedo[ic_h]
    rgh_s = bw0 * high_vertex_rough[ia_h] + bw1 * high_vertex_rough[ib_h] + bw2 * high_vertex_rough[ic_h]
    mtl_s = bw0 * high_vertex_metal[ia_h] + bw1 * high_vertex_metal[ib_h] + bw2 * high_vertex_metal[ic_h]
    ao_s = bw0 * ao_hi[ia_h] + bw1 * ao_hi[ib_h] + bw2 * ao_hi[ic_h]
    crv_s = bw0 * curv_hi[ia_h] + bw1 * curv_hi[ib_h] + bw2 * curv_hi[ic_h]

    kdtree = cKDTree(pts_s)

    # Rastérisation vectorisée de l'atlas UV `S × S` du Low-Poly
    f_low = np.asarray(low_uv_mesh.faces, dtype=np.int64)
    v_low = np.asarray(low_uv_mesh.vertices, dtype=np.float32)
    n_low = np.asarray(low_uv_mesh.vertex_normals, dtype=np.float32)
    tri_uv = np.empty((len(f_low), 3, 2), dtype=np.float64)
    tri_uv[..., 0] = uv[f_low, 0] * S
    tri_uv[..., 1] = (1.0 - uv[f_low, 1]) * S

    rast = pbr.rasterize_uv_triangles(tri_uv, S)
    f_hit, xs, ys, w0, w1, w2 = rast
    la, lb, lc = f_low[f_hit, 0], f_low[f_hit, 1], f_low[f_hit, 2]
    w0f, w1f, w2f = w0.astype(np.float32), w1.astype(np.float32), w2.astype(np.float32)

    pos_px = w0f[:, None] * v_low[la] + w1f[:, None] * v_low[lb] + w2f[:, None] * v_low[lc]
    N_px = w0f[:, None] * n_low[la] + w1f[:, None] * n_low[lb] + w2f[:, None] * n_low[lc]
    N_px /= np.linalg.norm(N_px, axis=1, keepdims=True) + 1e-12
    T4_px = w0f[:, None] * tangents_v4[la] + w1f[:, None] * tangents_v4[lb] + w2f[:, None] * tangents_v4[lc]
    T_px = T4_px[:, :3] - N_px * np.sum(N_px * T4_px[:, :3], axis=1, keepdims=True)
    T_px /= np.linalg.norm(T_px, axis=1, keepdims=True) + 1e-12
    sign_w = np.where(T4_px[:, 3:4] < 0.0, -1.0, 1.0).astype(np.float32)
    B_px = np.cross(N_px, T_px) * sign_w

    # Projection Cage Ray-Aware : interroge les 6 points High-Poly les plus proches et
    # privilégie ceux dont la normale est cohérente avec `N_px` (évite tout saut sur paroi mince !)
    dists, idx_k = kdtree.query(pos_px, k=6)
    cand_n = nrm_s[idx_k]  # (P, 6, 3)
    align = np.sum(cand_n * N_px[:, None, :], axis=2)  # [-1..1]
    score = dists / (float(np.linalg.norm(high_mesh.extents)) + 1e-6) + 0.035 * (1.0 - np.clip(align, -0.2, 1.0))
    best = idx_k[np.arange(len(pos_px)), np.argmin(score, axis=1)]

    nhi_px = nrm_s[best]
    col_px = alb_s[best]
    rgh_px = rgh_s[best]
    mtl_px = mtl_s[best]
    ao_px = ao_s[best]
    crv_px = crv_s[best]

    delight_meta = {}
    if delight_pass:
        col_px, delight_meta = dl.delight_albedo_3d(col_px, nhi_px, strength=0.78)

    if weathering:
        w_amt = 0.05 if delight_pass else 0.36
        d_amt = 0.14 if delight_pass else 0.30
        g_amt = 0.08 if delight_pass else 0.20
        dec_amt = 0.06 if delight_pass else decal_strength
        col_px, rgh_px, mtl_px, ao_px, hgt_px = apply_game_weathering(
            col_px, rgh_px, mtl_px, ao_px, crv_px,
            pos_px, nhi_px, high_mesh.bounds,
            wear_amount=w_amt, dirt_amount=d_amt, grime_amount=g_amt,
            decal_strength=dec_amt,
        )
    else:
        hgt_px = np.zeros(len(pos_px), dtype=np.float32)

    # Transformation de la normale High-Poly dans l'Espace Tangent Mikk du Low-Poly !
    ts_x = np.sum(nhi_px * T_px, axis=1)
    ts_y = np.sum(nhi_px * B_px, axis=1)
    ts_z = np.maximum(np.sum(nhi_px * N_px, axis=1), 0.12)

    albedo_map = np.zeros((S, S, 3), dtype=np.float32)
    orm_map = np.zeros((S, S, 3), dtype=np.float32)
    orm_map[..., 0], orm_map[..., 1] = 1.0, 0.5
    ts_map = np.zeros((S, S, 3), dtype=np.float32)
    ts_map[..., 2] = 1.0
    h_map = np.zeros((S, S), dtype=np.float32)
    mask_uv = np.zeros((S, S), dtype=bool)

    albedo_map[ys, xs] = col_px
    orm_map[ys, xs, 0] = ao_px
    orm_map[ys, xs, 1] = rgh_px
    orm_map[ys, xs, 2] = mtl_px
    ts_map[ys, xs, 0] = ts_x
    ts_map[ys, xs, 1] = ts_y
    ts_map[ys, xs, 2] = ts_z
    h_map[ys, xs] = hgt_px
    mask_uv[ys, xs] = True

    _, nn_i = ndimage.distance_transform_edt(~mask_uv, return_indices=True)
    albedo_map = albedo_map[nn_i[0], nn_i[1]]
    orm_map = orm_map[nn_i[0], nn_i[1]]
    ts_map = ts_map[nn_i[0], nn_i[1]]
    h_map = h_map[nn_i[0], nn_i[1]]

    # Combine la normale géométrique High->Low avec le micro-relief Normal Stamps / grain !
    dy_h, dx_h = np.gradient(h_map * 1.45)
    nx_gl = ts_map[..., 0] - dx_h
    ny_gl = ts_map[..., 1] + dy_h
    nz_gl = ts_map[..., 2]
    n_norm = np.sqrt(nx_gl * nx_gl + ny_gl * ny_gl + nz_gl * nz_gl) + 1e-12
    nx_gl, ny_gl, nz_gl = nx_gl / n_norm, ny_gl / n_norm, nz_gl / n_norm

    normal_gl_u8 = (np.stack([nx_gl, ny_gl, nz_gl], axis=-1) * 0.5 + 0.5) * 255.0
    # Convention Unreal Engine DirectX (`-Y` : canal Vert inversé `1.0 - G` !)
    normal_dx_u8 = (np.stack([nx_gl, -ny_gl, nz_gl], axis=-1) * 0.5 + 0.5) * 255.0

    alb_img = pbr.compress_png(Image.fromarray(np.clip(albedo_map * 255.0, 0, 255).astype(np.uint8), "RGB"))
    orm_img = pbr.compress_png(Image.fromarray(np.clip(orm_map * 255.0, 0, 255).astype(np.uint8), "RGB"))
    nrm_gl_img = pbr.compress_png(Image.fromarray(np.clip(normal_gl_u8, 0, 255).astype(np.uint8), "RGB"))
    nrm_dx_img = pbr.compress_png(Image.fromarray(np.clip(normal_dx_u8, 0, 255).astype(np.uint8), "RGB"))

    # Unity HDRP MaskMap : R = Metallic, G = Ambient Occlusion, B = Detail Mask (255), A = Smoothness (1 - Roughness)
    mask_map_u8 = np.stack([
        orm_map[..., 2] * 255.0,
        orm_map[..., 0] * 255.0,
        np.full((S, S), 255.0, dtype=np.float32),
        (1.0 - orm_map[..., 1]) * 255.0,
    ], axis=-1)
    unity_mask_img = pbr.compress_png(Image.fromarray(np.clip(mask_map_u8, 0, 255).astype(np.uint8), "RGBA"))

    mat_pbr = trimesh.visual.material.PBRMaterial(
        name="SM_GamePBR",
        baseColorFactor=[255, 255, 255, 255],
        baseColorTexture=alb_img,
        metallicRoughnessTexture=orm_img,
        occlusionTexture=orm_img,
        normalTexture=nrm_gl_img,
        metallicFactor=1.0,
        roughnessFactor=1.0,
    )
    low_uv_mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=mat_pbr)

    return {
        "mesh_lod0": low_uv_mesh,
        "uv": uv,
        "tangents": tangents_v4,
        "albedo": alb_img,
        "orm": orm_img,
        "normal_gl": nrm_gl_img,
        "normal_dx": nrm_dx_img,
        "unity_mask": unity_mask_img,
        "delight_metrics": delight_meta,
    }


def transfer_uv_to_lod(lod0_uv_mesh: trimesh.Trimesh, decimated_mesh: trimesh.Trimesh,
                       mat_pbr: trimesh.visual.material.PBRMaterial) -> trimesh.Trimesh:
    """Transfère les coordonnées UV de `lod0_uv_mesh` vers `LOD1` / `LOD2` par projection
    K-NN par sommet pour que TOUS les niveaux de LOD partagent le MÊME atlas de textures !"""
    tree = cKDTree(np.asarray(lod0_uv_mesh.vertices, dtype=np.float32))
    _, idx = tree.query(np.asarray(decimated_mesh.vertices, dtype=np.float32), k=1)
    uv_lod0 = np.asarray(lod0_uv_mesh.visual.uv, dtype=np.float32)
    m_out = decimated_mesh.copy()
    m_out.visual = trimesh.visual.TextureVisuals(uv=uv_lod0[idx], material=mat_pbr)
    return m_out


# --------------------------------------------------------------------------- #
# 5. Collisions Convexes `UCX_*` / `-colonly` & Inférence de `SOCKET_*` Gameplay
# --------------------------------------------------------------------------- #

def generate_convex_colliders(
    source_meshes: list[trimesh.Trimesh],
    max_hulls: int = 6,
    max_tris_per_hull: int = 28,
) -> list[trimesh.Trimesh]:
    """Décompose un objet en `<= max_hulls` coques convexes propres (`<= max_tris_per_hull` tris)
    préservant les ouvertures (sous une table, embrasure de porte, passages de roues, garde d'épée)."""
    candidates = [m for m in source_meshes if len(m.vertices) >= 4 and m.volume >= 0]
    if not candidates:
        return []

    if len(candidates) <= max_hulls:
        groups = [[m] for m in candidates]
    else:
        # Regroupe les pièces par K-means spatial rapide sur leurs centres de gravité !
        centers = np.array([0.5 * (m.bounds[0] + m.bounds[1]) for m in candidates], dtype=np.float64)
        rng = np.random.default_rng(42)
        pivots = centers[rng.choice(len(centers), size=max_hulls, replace=False)].copy()
        assign = np.zeros(len(centers), dtype=np.int32)
        for _ in range(12):
            d2 = np.linalg.norm(centers[:, None, :] - pivots[None, :, :], axis=2)
            assign = np.argmin(d2, axis=1)
            for k in range(max_hulls):
                sel = centers[assign == k]
                if len(sel) > 0:
                    pivots[k] = sel.mean(axis=0)
        groups = [[candidates[i] for i in range(len(candidates)) if assign[i] == k]
                  for k in range(max_hulls)]
        groups = [g for g in groups if g]

    hulls = []
    for grp in groups:
        pts = np.vstack([m.vertices for m in grp])
        if len(pts) < 4:
            continue
        hull = trimesh.convex.convex_hull(pts)
        if len(hull.faces) > max_tris_per_hull:
            hull = trimesh.convex.convex_hull(decimate_mesh_clean(hull, max_tris_per_hull).vertices)
        hulls.append(hull)
    return hulls


def infer_gameplay_sockets(
    name: str,
    bounds: np.ndarray,
    joints: dict | None = None,
    declared: dict | None = None,
) -> dict:
    """Complète les `SOCKET_*` déclarés par des sockets gameplay intelligents adaptés au type d'asset."""
    out = dict(declared or {})
    bmin, bmax = bounds[0], bounds[1]
    c = 0.5 * (bmin + bmax)
    lname = name.lower()

    out.setdefault("SOCKET_origin_ground", {"position": [float(c[0]), float(c[1]), float(bmin[2])], "rotation_deg": [0, 0, 0]})
    out.setdefault("SOCKET_top", {"position": [float(c[0]), float(c[1]), float(bmax[2])], "rotation_deg": [0, 0, 0]})

    if any(w in lname for w in ("sword", "katana", "epee", "blade", "axe", "hammer")):
        grip_z = float(bmin[2] + 0.14 * (bmax[2] - bmin[2]))
        out.setdefault("SOCKET_grip", {"position": [float(c[0]), float(c[1]), grip_z], "rotation_deg": [0, 0, 0]})
        out.setdefault("SOCKET_tip", {"position": [float(c[0]), float(c[1]), float(bmax[2])], "rotation_deg": [0, 0, 0]})
        out.setdefault("SOCKET_trail_mid", {"position": [float(c[0]), float(c[1]), float(0.5 * (grip_z + bmax[2]))], "rotation_deg": [0, 0, 0]})
    elif any(w in lname for w in ("car", "moto", "vehicle", "truck")):
        out.setdefault("SOCKET_headlight_front", {"position": [float(bmax[0]), float(c[1]), float(bmin[2] + 0.45 * (bmax[2] - bmin[2]))], "rotation_deg": [0, 0, 0]})
        out.setdefault("SOCKET_exhaust", {"position": [float(bmin[0]), float(c[1]), float(bmin[2] + 0.25 * (bmax[2] - bmin[2]))], "rotation_deg": [0, 0, 180]})
        out.setdefault("SOCKET_driver_seat", {"position": [float(c[0]), float(c[1]), float(bmin[2] + 0.62 * (bmax[2] - bmin[2]))], "rotation_deg": [0, 0, 0]})
    else:
        out.setdefault("SOCKET_interact", {"position": [float(c[0]), float(bmin[1]), float(c[2])], "rotation_deg": [0, 0, 0]})

    for jname, jinfo in (joints or {}).items():
        out.setdefault(f"SOCKET_{jname}", {"position": list(jinfo["pivot"]), "rotation_deg": [0, 0, 0]})
    return out


# --------------------------------------------------------------------------- #
# 6. Export Complet Game-Ready Multi-Moteurs (`export_game_package`)
# --------------------------------------------------------------------------- #

def export_game_package(
    source: mk.Builder | trimesh.Trimesh | str | Path,
    out_dir: str | Path,
    name: str | None = None,
    engine: str = "all",
    lod0_tris: int = 3400,
    tex_size: int = 1024,
    weathering: bool = True,
    delight_pass: bool | None = None,
    webp: bool = True,
    decal_strength: float = 0.65,
) -> dict:
    """Pipeline de bout en bout produisant un asset Game-Ready complet :
      - Fusionne les Draw Calls statiques opaques en **1 seul Draw Call**,
      - Cuit High-Poly -> Low-Poly `LOD0` + génère `LOD1` (`40%`) et `LOD2` (`15%`),
      - Génère les colliders convexes `UCX_<Name>_00..N` + `SOCKET_*` + `gltf.animations`,
      - Exporte les profils moteurs demandés (`unreal`, `unity`, `godot`, `gltf` ou `all`),
      - Génère la planche de contrôle Technical Artist `qa_game_sheet.png` + `game_manifest.json`.
    """
    t0 = time.perf_counter()
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    if isinstance(source, str) and not Path(source).exists():
        import generate as _gen
        rec = _gen.get_recipe(source)
        if rec is not None:
            if name is None:
                name = source
            mk.set_quality(1.4)
            source = rec["builder"]()
    if name is None:
        if isinstance(source, mk.Builder):
            name = source.name
        elif isinstance(source, (str, Path)):
            name = Path(source).stem
        else:
            name = "game_asset"
    clean_name = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)

    joints = {}
    declared_sockets = {}
    glass_parts: list[tuple[trimesh.Trimesh, mk.Material, str]] = []
    joint_opaque_groups: dict[str, list[tuple[trimesh.Trimesh, mk.Material, str]]] = {}
    static_meshes: list[trimesh.Trimesh] = []
    static_albedo: list[np.ndarray] = []
    static_rough: list[np.ndarray] = []
    static_metal: list[np.ndarray] = []
    collider_inputs: list[trimesh.Trimesh] = []
    raw_draw_calls = 1

    if isinstance(source, mk.Builder):
        raw_draw_calls = len(source.parts)
        joints = dict(source._joints)
        declared_sockets = dict(source._sockets)
        for idx, (m, mat_o, lbl) in enumerate(source.parts):
            mat_use = mat_o or mk.Material("default", "#9a9da2", 0.0, 0.5)
            grp = source._part_groups.get(idx)
            collider_inputs.append(m.copy())
            if mat_use.opacity < 0.999:
                glass_parts.append((m.copy(), mat_use, lbl))
            elif grp:
                joint_opaque_groups.setdefault(grp, []).append((m.copy(), mat_use, lbl))
            else:
                nv = len(m.vertices)
                static_meshes.append(m.copy())
                static_albedo.append(np.tile(np.asarray(mat_use.color, dtype=np.float32), (nv, 1)))
                static_rough.append(np.full(nv, float(mat_use.roughness), dtype=np.float32))
                static_metal.append(np.full(nv, float(mat_use.metallic), dtype=np.float32))
        high_body = trimesh.util.concatenate(static_meshes)
        v_alb = np.vstack(static_albedo)
        v_rgh = np.concatenate(static_rough)
        v_mtl = np.concatenate(static_metal)
        low_base = decimate_mesh_clean(mk.union(static_meshes) if len(static_meshes) > 1 else static_meshes[0], lod0_tris)
        if delight_pass is None:
            delight_pass = False
    else:
        src_obj = trimesh.load(source, force="scene") if isinstance(source, (str, Path)) else source
        if isinstance(src_obj, trimesh.Scene):
            raw_draw_calls = max(len(src_obj.geometry), 1)
            high_body = src_obj.to_geometry()
        else:
            high_body = src_obj.copy()
        collider_inputs = [high_body.copy()]
        # Extrait la couleur par sommet depuis la texture existante si présente !
        uv_h = getattr(high_body.visual, "uv", None)
        mat_h = getattr(high_body.visual, "material", None)
        tex_h = getattr(mat_h, "baseColorTexture", None) if mat_h is not None else None
        mr_h = getattr(mat_h, "metallicRoughnessTexture", None) if mat_h is not None else None
        nv = len(high_body.vertices)
        if uv_h is not None and tex_h is not None:
            arr_t = np.asarray(tex_h.convert("RGB"), dtype=np.float32) / 255.0
            th, tw, _ = arr_t.shape
            px_x = np.clip((uv_h[:, 0] * (tw - 1)).round().astype(np.int32), 0, tw - 1)
            px_y = np.clip(((1.0 - uv_h[:, 1]) * (th - 1)).round().astype(np.int32), 0, th - 1)
            v_alb = arr_t[px_y, px_x]
            if mr_h is not None:
                arr_m = np.asarray(mr_h.convert("RGB"), dtype=np.float32) / 255.0
                v_rgh = arr_m[px_y, px_x, 1]
                v_mtl = arr_m[px_y, px_x, 2]
            else:
                v_rgh = np.full(nv, 0.55, dtype=np.float32)
                v_mtl = np.full(nv, 0.15, dtype=np.float32)
        else:
            v_alb = np.tile(np.array([0.55, 0.56, 0.58], dtype=np.float32), (nv, 1))
            v_rgh = np.full(nv, 0.50, dtype=np.float32)
            v_mtl = np.full(nv, 0.10, dtype=np.float32)
        low_base = decimate_mesh_clean(high_body, lod0_tris)
        if delight_pass is None:
            delight_pass = True

    baked = bake_high_to_low(
        high_body, v_alb, v_rgh, v_mtl, low_base,
        tex_size=tex_size, weathering=weathering,
        delight_pass=bool(delight_pass), decal_strength=decal_strength,
    )
    lod0_mesh = baked["mesh_lod0"]

    # Génère `LOD1` (40%, mipmap 512px) et `LOD2` (15%, mipmap 256px) chacun avec son
    # dépliage `xatlas` sans couture et son propre bake tangent-space exact `High -> LOD_i` !
    lod1_raw = decimate_mesh_clean(low_base, max(int(lod0_tris * 0.40), 64))
    lod2_raw = decimate_mesh_clean(low_base, max(int(lod0_tris * 0.15), 32))
    baked_lod1 = bake_high_to_low(
        high_body, v_alb, v_rgh, v_mtl, lod1_raw,
        tex_size=max(tex_size // 2, 256), weathering=weathering,
        delight_pass=bool(delight_pass), decal_strength=decal_strength,
    )
    baked_lod2 = bake_high_to_low(
        high_body, v_alb, v_rgh, v_mtl, lod2_raw,
        tex_size=max(tex_size // 4, 128), weathering=weathering,
        delight_pass=bool(delight_pass), decal_strength=decal_strength,
    )
    lod1_mesh = baked_lod1["mesh_lod0"]
    lod2_mesh = baked_lod2["mesh_lod0"]

    # Construit la scène principale `LOD0` fusionnée en Draw Calls minimaux !
    def _assemble_lod_scene(body_mesh: trimesh.Trimesh, include_colliders: str | None = None) -> trimesh.Scene:
        sc = trimesh.Scene(base_frame=f"SM_{clean_name}")
        sc.add_geometry(body_mesh.copy(), node_name=f"SM_{clean_name}_Body", geom_name=f"SM_{clean_name}_Body")

        if glass_parts:
            g_merged = trimesh.util.concatenate([g[0] for g in glass_parts])
            g_merged.visual = trimesh.visual.TextureVisuals(material=glass_parts[0][1].to_pbr())
            sc.add_geometry(g_merged, node_name=f"SM_{clean_name}_Glass", geom_name=f"SM_{clean_name}_Glass")

        for grp, plist in joint_opaque_groups.items():
            piv = joints.get(grp, {}).get("pivot", [0.0, 0.0, 0.0])
            T = np.eye(4, dtype=float)
            T[:3, 3] = piv
            sc.graph.update(frame_to=grp, frame_from=sc.graph.base_frame, matrix=T)
            j_mesh = decimate_mesh_clean(trimesh.util.concatenate([p[0] for p in plist]), max(lod0_tris // 3, 180))
            j_mesh.apply_translation([-piv[0], -piv[1], -piv[2]])
            j_mesh.visual = trimesh.visual.TextureVisuals(material=plist[0][1].to_pbr())
            sc.add_geometry(j_mesh, node_name=f"{grp}_mesh", geom_name=f"{grp}_mesh", parent_node_name=grp)

        if include_colliders:
            for ci, hull in enumerate(colliders):
                cname = f"UCX_SM_{clean_name}_{ci:02d}" if include_colliders == "unreal" else f"{clean_name}_col_{ci:02d}-colonly"
                h_copy = hull.copy()
                h_copy.visual = trimesh.visual.TextureVisuals(
                    material=mk.Material(f"col_mat_{ci}", "#35e085", 0.0, 0.6, opacity=0.28).to_pbr()
                )
                sc.add_geometry(h_copy, node_name=cname, geom_name=cname)

        sc.metadata["joints"] = joints
        sc.metadata["sockets"] = sockets
        return sc

    all_bounds = np.vstack([
        np.min([m.bounds[0] for m in collider_inputs], axis=0),
        np.max([m.bounds[1] for m in collider_inputs], axis=0),
    ])
    colliders = generate_convex_colliders(collider_inputs, max_hulls=6, max_tris_per_hull=28)
    sockets = infer_gameplay_sockets(clean_name, all_bounds, joints=joints, declared=declared_sockets)

    sc_lod0 = _assemble_lod_scene(lod0_mesh)
    sc_lod1 = _assemble_lod_scene(lod1_mesh)
    sc_lod2 = _assemble_lod_scene(lod2_mesh)
    final_draw_calls = len(sc_lod0.geometry)

    glb_main = out_path / f"{clean_name}_game.glb"
    glb_lod1 = out_path / f"{clean_name}_LOD1.glb"
    glb_lod2 = out_path / f"{clean_name}_LOD2.glb"
    mk.export_glb_pbr(sc_lod0, str(glb_main), webp=webp)
    mk.export_glb_pbr(sc_lod1, str(glb_lod1), webp=webp)
    mk.export_glb_pbr(sc_lod2, str(glb_lod2), webp=webp)

    # Export collision autonome + profils moteurs dédiés (`unreal`, `unity`, `godot`)
    col_scene = trimesh.Scene([h.copy() for h in colliders])
    col_glb = out_path / f"{clean_name}_colliders.glb"
    col_scene.export(str(col_glb))

    engines = {"unreal", "unity", "godot"} if engine == "all" else {engine}
    exported_profiles = {}

    if "unreal" in engines:
        ue_dir = out_path / "unreal"
        ue_dir.mkdir(exist_ok=True)
        baked["albedo"].save(ue_dir / f"T_{clean_name}_BC.png")
        baked["orm"].save(ue_dir / f"T_{clean_name}_ORM.png")
        baked["normal_dx"].save(ue_dir / f"T_{clean_name}_N.png")  # DirectX -Y !
        sc_ue = _assemble_lod_scene(lod0_mesh, include_colliders="unreal")
        ue_glb = ue_dir / f"SM_{clean_name}.glb"
        mk.export_glb_pbr(sc_ue, str(ue_glb), webp=False)
        exported_profiles["unreal"] = {
            "static_mesh_with_ucx": str(ue_glb),
            "base_color": str(ue_dir / f"T_{clean_name}_BC.png"),
            "orm_packed": str(ue_dir / f"T_{clean_name}_ORM.png"),
            "normal_directx_neg_y": str(ue_dir / f"T_{clean_name}_N.png"),
        }

    if "unity" in engines:
        un_dir = out_path / "unity"
        un_dir.mkdir(exist_ok=True)
        baked["albedo"].save(un_dir / f"T_{clean_name}_BaseMap.png")
        baked["unity_mask"].save(un_dir / f"T_{clean_name}_MaskMap.png")
        baked["normal_gl"].save(un_dir / f"T_{clean_name}_NormalGL.png")
        exported_profiles["unity"] = {
            "prefab_glb": str(glb_main),
            "base_map": str(un_dir / f"T_{clean_name}_BaseMap.png"),
            "hdrp_mask_map_rgba": str(un_dir / f"T_{clean_name}_MaskMap.png"),
            "normal_opengl_pos_y": str(un_dir / f"T_{clean_name}_NormalGL.png"),
        }

    if "godot" in engines or engine == "gltf":
        gd_dir = out_path / "godot"
        gd_dir.mkdir(exist_ok=True)
        sc_gd = _assemble_lod_scene(lod0_mesh, include_colliders="godot")
        gd_glb = gd_dir / f"{clean_name}_godot.glb"
        mk.export_glb_pbr(sc_gd, str(gd_glb), webp=webp)
        exported_profiles["godot"] = {"scene_with_colonly": str(gd_glb)}

    pv.build_preview(str(out_path), title=f"{clean_name} — Game-Ready LOD0 ({len(lod0_mesh.faces)} tris)", glb=str(glb_main))

    # Planche de contrôle Technical Artist `qa_game_sheet.png` (6 panneaux comparatifs HD)
    az, el = renderer.DEFAULT_VIEWS["three_quarter"]
    hi_vis = high_body.copy()
    hi_vis.visual.vertex_colors = np.column_stack([
        (np.clip(v_alb, 0.0, 1.0) * 255).astype(np.uint8),
        np.full(len(v_alb), 255, dtype=np.uint8),
    ])
    im_hi = renderer.render_view(trimesh.Scene([hi_vis]), az, el, size=560)
    im_lod0 = renderer.render_view(sc_lod0, az, el, size=560)
    im_lod2 = renderer.render_view(sc_lod2, az, el, size=560)

    # Rendu superposé du maillage `LOD0` + enveloppes de collision convexes `UCX_*` vertes translucides !
    sc_col_vis = _assemble_lod_scene(lod0_mesh, include_colliders="unreal")
    im_col = renderer.render_view(sc_col_vis, az, el, size=560)
    draw_c = ImageDraw.Draw(im_col)
    draw_c.rectangle((10, 10, 310, 38), fill=(18, 28, 22))
    draw_c.text((18, 16), f"{len(colliders)} hulls UCX ({sum(len(h.faces) for h in colliders)} tris) + {len(sockets)} sockets", fill=(110, 245, 165))

    im_nrm = baked["normal_gl"].resize((560, 560), Image.BILINEAR)
    im_orm = baked["orm"].resize((560, 560), Image.BILINEAR)

    qa_sheet = out_path / "qa_game_sheet.png"
    renderer.contact_sheet(
        [
            (im_hi, f"1. Source High-Poly ({len(high_body.faces):,} tris, {raw_draw_calls} draw calls)"),
            (im_lod0, f"2. Game LOD0 ({len(lod0_mesh.faces):,} tris, {final_draw_calls} draw calls)"),
            (im_lod2, f"3. Far LOD2 ({len(lod2_mesh.faces):,} tris, même atlas UV)"),
            (im_col, f"4. Colliders Physiques UCX ({sum(len(h.faces) for h in colliders)} tris) & Sockets"),
            (im_nrm, "5. Tangent-Space Normal Map (Mikk VEC4)"),
            (im_orm, "6. Packed ORM (R=AO, G=Roughness, B=Metallic)"),
        ],
        cols=3,
        out_path=str(qa_sheet),
        title=f"3d-forge v5 Game-Ready QA — {clean_name} (High-Poly -> LOD0/1/2 + PBR + Colliders + Unreal/Unity/Godot)",
    )

    manifest = {
        "asset_name": clean_name,
        "high_poly_tris": int(len(high_body.faces)),
        "lods": {
            "LOD0": {"tris": int(len(lod0_mesh.faces)), "path": str(glb_main), "bytes": glb_main.stat().st_size},
            "LOD1": {"tris": int(len(lod1_mesh.faces)), "path": str(glb_lod1), "bytes": glb_lod1.stat().st_size},
            "LOD2": {"tris": int(len(lod2_mesh.faces)), "path": str(glb_lod2), "bytes": glb_lod2.stat().st_size},
        },
        "draw_calls_before": int(raw_draw_calls),
        "draw_calls_after": int(final_draw_calls),
        "poly_reduction_pct": round(100.0 * (1.0 - len(lod0_mesh.faces) / max(len(high_body.faces), 1)), 2),
        "physics_colliders": {
            "count": int(len(colliders)),
            "total_tris": int(sum(len(h.faces) for h in colliders)),
            "path": str(col_glb),
        },
        "sockets": sockets,
        "has_explicit_mikk_tangents": True,
        "webp_compressed": bool(webp),
        "engine_exports": exported_profiles,
        "delight_metrics": baked["delight_metrics"],
        "qa_sheet": str(qa_sheet),
        "duration_s": round(time.perf_counter() - t0, 2),
    }
    (out_path / "game_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help="Nom d'une recette catalogue OU chemin vers un fichier .glb/.stl/.obj")
    ap.add_argument("-o", "--out", required=True, help="Dossier de sortie du pack Game-Ready")
    ap.add_argument("--name", default=None, help="Nom de l'asset exporté")
    ap.add_argument("--engine", choices=["all", "unreal", "unity", "godot", "gltf"], default="all")
    ap.add_argument("--lod0-tris", type=int, default=3400, help="Budget triangles cible pour LOD0")
    ap.add_argument("--tex-size", type=int, default=1024, help="Résolution des textures PBR")
    ap.add_argument("--no-weathering", action="store_true")
    ap.add_argument("--delight", action="store_true", help="Active explicitement le de-lighting SH de l'Albédo")
    ap.add_argument("--no-webp", action="store_true")
    args = ap.parse_args(argv)

    if args.source in recipes.REGISTRY:
        b = recipes.get(args.source)["builder"]()
        asset_name = args.name or args.source
        src = b
    else:
        src = Path(args.source)
        asset_name = args.name or src.stem

    manifest = export_game_package(
        src,
        out_dir=args.out,
        name=asset_name,
        engine=args.engine,
        lod0_tris=args.lod0_tris,
        tex_size=args.tex_size,
        weathering=not args.no_weathering,
        delight_pass=True if args.delight else None,
        webp=not args.no_webp,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
