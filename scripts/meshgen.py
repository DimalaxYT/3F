#!/usr/bin/env python3
"""
meshgen — génération 3D type Meshy, 100% déterministe, zéro API.

Le LLM ne "code" plus l'objet : il l'IMAGINE sous forme de vues ASCII
(face / profil / dessus) peintes avec des lettres de matériaux, exactement
comme Meshy synthétise des vues plausibles puis les re-projette.

Pipeline (équivalent déterministe des 7 étapes Meshy) :
  1. Représentation interne : silhouettes multi-vues ASCII + palette PBR.
  2. Synthèse multi-vues : les 3 vues servent de contraintes mutuelles
     (une forme doit être cohérente face/profil/dessus pour exister).
  3. Volume : visual hull (intersection des extrusions) -> grille voxels,
     votes de matériaux multi-vues -> volume d'étiquettes.
  4. Géométrie : marching cubes -> lissage Taubin -> décimation quadrique
     (budget triangles) -> réparation (watertight).
  5. UV : unwrap xatlas (coutures auto, atlas compact).
  6. Textures PBR : peinture procédurale 3D->2D re-projetée dans l'atlas
     (albedo / roughness / metallic / normal) : rouille, grain bois,
     cuir brisé, usure des arêtes, micro-variations.
  7. Cohérence : IoU des silhouettes re-projetées vs vues d'entrée,
     watertight, budget, composants. Exports GLB/OBJ/STL/USDZ + PNG.

Usage :
    python meshgen.py spec.json --out output/mon_objet
Format du spec : voir SKILL.md section "Workflow B — Génération multi-vues".
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
from PIL import Image
from scipy import ndimage
from skimage import measure

import trimesh

import renderer

EMPTY = {".", " ", ""}


# --------------------------------------------------------------------------
# Bruit 3D déterministe (value noise + fBm) — aucune dépendance externe
# --------------------------------------------------------------------------

def _hash3(ix, iy, iz, seed):
    h = (ix.astype(np.int64) * 374761393
         + iy.astype(np.int64) * 668265263
         + iz.astype(np.int64) * 1442695041
         + np.int64(seed) * 2654435761) & 0x7FFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0x7FFFFFFF
    return ((h ^ (h >> 16)).astype(np.float64)) / 2147483647.0


def value_noise(x, y, z, seed=0):
    """Value noise 3D lisse (smoothstep entre 8 coins de la grille)."""
    ix, iy, iz = np.floor(x), np.floor(y), np.floor(z)
    fx, fy, fz = x - ix, y - iy, z - iz
    ux = fx * fx * (3 - 2 * fx)
    uy = fy * fy * (3 - 2 * fy)
    uz = fz * fz * (3 - 2 * fz)
    c000 = _hash3(ix, iy, iz, seed)
    c100 = _hash3(ix + 1, iy, iz, seed)
    c010 = _hash3(ix, iy + 1, iz, seed)
    c110 = _hash3(ix + 1, iy + 1, iz, seed)
    c001 = _hash3(ix, iy, iz + 1, seed)
    c101 = _hash3(ix + 1, iy, iz + 1, seed)
    c011 = _hash3(ix, iy + 1, iz + 1, seed)
    c111 = _hash3(ix + 1, iy + 1, iz + 1, seed)
    x00 = c000 + (c100 - c000) * ux
    x10 = c010 + (c110 - c010) * ux
    x01 = c001 + (c101 - c001) * ux
    x11 = c011 + (c111 - c011) * ux
    y0 = x00 + (x10 - x00) * uy
    y1 = x01 + (x11 - x01) * uy
    return y0 + (y1 - y0) * uz


def fbm(x, y, z, octaves=4, lacunarity=2.0, gain=0.5, seed=0):
    """Fractional Brownian motion : bruit multi-octaves, borné ~[0,1]."""
    total = np.zeros_like(x, dtype=np.float64)
    amp, freq, norm = 1.0, 1.0, 0.0
    for o in range(octaves):
        total += amp * value_noise(x * freq, y * freq, z * freq, seed + o * 101)
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / max(1e-9, (e1 - e0)), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _frac(x):
    return x - np.floor(x)


# --------------------------------------------------------------------------
# 1. Représentation interne : parsing des vues ASCII
# --------------------------------------------------------------------------

class SpecError(ValueError):
    pass


def parse_view(rows, palette_ids, view_name):
    """Vue ASCII -> (mask H×W bool, zones H×W int).
    zones : -1 = vide, sinon index palette ('#' = 0 = matériau principal)."""
    if not rows or not isinstance(rows, list):
        raise SpecError(f"vue '{view_name}' : liste de lignes attendue")
    W = max(len(r) for r in rows)
    if W < 2:
        raise SpecError(f"vue '{view_name}' : trop étroite")
    grid = np.full((len(rows), W), -1, dtype=np.int32)
    for r, line in enumerate(rows):
        for c, ch in enumerate(line):
            if ch in EMPTY:
                continue
            if ch == "#":
                grid[r, c] = 0
            elif ch in palette_ids:
                grid[r, c] = palette_ids.index(ch)
            else:
                raise SpecError(
                    f"vue '{view_name}' ligne {r} col {c} : caractère '{ch}' "
                    f"absent de la palette {'/'.join(palette_ids)} ('.' ou espace = vide)")
    return grid != -1, grid


def _resize_nearest(arr, shape):
    im = Image.fromarray(arr)
    im = im.resize((shape[1], shape[0]), Image.NEAREST)
    return np.asarray(im)


# --------------------------------------------------------------------------
# 2-3. Visual hull + votes de matériaux
# --------------------------------------------------------------------------

def build_volumes(spec):
    """Extrude les 3 vues et intersecte -> (occ, zone, dims grille).
    Axes Z-up (convention skill) : hauteur = Z, volume indexé [x, y, z]."""
    pal = [m["id"] for m in spec["palette"]]
    mf, zf = parse_view(spec["views"]["front"], pal, "front")
    ms, zs = parse_view(spec["views"]["side"], pal, "side")
    mt, zt = parse_view(spec["views"]["top"], pal, "top")

    R = int(spec.get("res", 80))
    gx = max(4, round(R * mf.shape[1] / mf.shape[0]))
    gz = R
    gy = max(4, round(R * ms.shape[1] / ms.shape[0]))

    # front : colonnes->X, lignes->Z (ligne 0 en haut = +Z)
    mf_g = _resize_nearest(mf.astype(np.uint8), (gz, gx)).astype(bool)
    zf_g = _resize_nearest(zf.astype(np.int32), (gz, gx))
    A_f = np.broadcast_to(mf_g.T[:, None, :], (gx, gy, gz))
    Z_f = np.broadcast_to(zf_g.T[:, None, :], (gx, gy, gz))
    # side : colonnes->Y (arrière->avant), lignes->Z
    ms_g = _resize_nearest(ms.astype(np.uint8), (gz, gy)).astype(bool)
    zs_g = _resize_nearest(zs.astype(np.int32), (gz, gy))
    A_s = np.broadcast_to(ms_g.T[None, :, :], (gx, gy, gz))
    Z_s = np.broadcast_to(zs_g.T[None, :, :], (gx, gy, gz))
    # top : colonnes->X, lignes->Y (ligne 0 = arrière)
    mt_g = _resize_nearest(mt.astype(np.uint8), (gy, gx)).astype(bool)
    zt_g = _resize_nearest(zt.astype(np.int32), (gy, gx))
    A_t = np.broadcast_to(mt_g.T[:, :, None], (gx, gy, gz))
    Z_t = np.broadcast_to(zt_g.T[:, :, None], (gx, gy, gz))

    occ = A_f & A_s & A_t
    if not occ.any():
        raise SpecError("visual hull vide : les 3 vues ne se recouvrent pas")

    occ = _fill_closed_cavities(occ, spec)

    # symmetry_x miroite l'objet en X et fait l'union : utile pour dessiner
    # une moitié, mais il DUPLIQUE silencieusement tout détail asymétrique
    # (antenne décentrée, pupille, emblème). On prévient si les vues
    # décrivent un objet visiblement asymétrique.
    if spec.get("symmetry_x", True):
        diff = int((occ ^ occ[::-1, :, :]).sum())
        if diff * 20 > int(occ.sum()):
            print(f"  ⚠ symmetry_x=true mais les vues sont asymétriques "
                  f"({diff} voxels hors miroir) : les détails décentrés "
                  f"seront dupliqués en miroir — symmetry_x: false si "
                  f"non voulu")
        occ = occ | occ[::-1, :, :]

    # votes de matériaux (une vue = un vote, majorité, ex æquo -> palette order)
    votes = np.stack([Z_f, Z_s, Z_t])          # (3, X, Y, Z)
    valid = votes >= 0
    P = len(pal)
    counts = np.zeros((P,) + occ.shape, dtype=np.int16)
    for p in range(P):
        counts[p] = ((votes == p) & valid).sum(0)
    zone = counts.argmax(0).astype(np.int8)
    zone[~occ] = -1

    if spec.get("symmetry_x", True):
        occ = occ | occ[::-1, :, :]
        zm = zone[::-1, :, :]
        zone = np.where(zone >= 0, zone, zm)   # union, on garde le vote existant

    return occ, zone, (gx, gy, gz), (mf, ms, mt)


# --------------------------------------------------------------------------
# 4. Géométrie : marching cubes + lissage + décimation
# --------------------------------------------------------------------------

def _sample_labels(zone_up, coords):
    """Labels aux sommets, avec réparation des frontières MC.

    Les sommets de surface tombent souvent sur le VOXEL VIDE juste devant
    la face (rint de la frontière marching cubes). Sans réparation, ces
    sommets seraient clippés vers le matériau principal et toute zone
    peinte au centre d'une face large (fuller, décor) serait perdue.
    -> label du voxel occupé le plus proche (distance transform 3D).
    """
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
    """Supprime les îlots de triangles issus du marching cubes sur les
    objets à plaques fines (tôle, grilles, boîtes creuses) : le lissage
    Taubin y sectionne la coque et laisse des fragments de 2-20 faces
    collés au corps. Critère conservateur : un composant est un débris
    s'il a moins de `debris_min_faces` faces (50 par défaut — une antenne
    cylindrique, un rivet ou une sangle en gardent toujours plus de 50).
    Le nombre de débris supprimés est tracé dans mesh.metadata pour le
    report.json."""
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
    """Les vues décrivent l'ENVELOPPE extérieure de l'objet : une cavité
    FERMÉE ne peut donc être qu'une erreur de dessin (coque dessinée en
    anneau, pensée comme « creuse »). On comble ces cavités ; les creux
    ouverts (vase, bol, coque de bateau) restent connectés à l'extérieur
    et ne sont pas affectés. Désactivable avec fill_cavities: false."""
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
    # padding : marching cubes laisse des surfaces ouvertes sur les bords
    # du tableau si le volume y touche -> on entoure de cellules vides
    P = 3
    occ = np.pad(occ, P, constant_values=False)
    zone = np.pad(zone, P, constant_values=-1)

    up = int(spec.get("upsample", 2))
    vol = ndimage.zoom(occ.astype(np.float32), up, order=1)
    zone_up = np.repeat(np.repeat(np.repeat(zone, up, 0), up, 1), up, 2)

    verts, faces, _, _ = measure.marching_cubes(
        vol, level=float(spec.get("mc_level", 0.5)))
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    trimesh.repair.fix_normals(mesh)
    trimesh.repair.fill_holes(mesh)

    n_smooth = int(spec.get("smooth", 12))
    trimesh.smoothing.filter_taubin(mesh, lamb=0.5, nu=-0.53,
                                    iterations=n_smooth)
    mesh.process(validate=True)
    _remove_debris(mesh, spec)

    # étiquettes matériaux par sommet (réparation frontières : voir
    # _sample_labels — sinon les zones peintes au centre des faces
    # larges sont perdues au profit du matériau principal)
    v_labels = _sample_labels(zone_up, np.rint(mesh.vertices).astype(np.int64))

    # échelle physique : la hauteur (Z) du bbox vaut size_m
    size_m = float(spec.get("size_m", 1.0))
    ext = mesh.bounds[1] - mesh.bounds[0]
    scale = size_m / max(1e-9, ext[2])
    mesh.apply_scale(scale)

    # décimation vers le budget triangles (essais à budgets croissants ;
    # si tout perce le mesh, on garde le mesh MC intégral)
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
                    np.rint(mesh.vertices / scale).astype(np.int64))
                break
        if not mesh.is_watertight:
            mesh, v_labels = keep, keep_labels

    return mesh, v_labels


# --------------------------------------------------------------------------
# 5. UV unwrap
# --------------------------------------------------------------------------

def unwrap(mesh, v_labels):
    import xatlas
    vm, ft, uv = xatlas.parametrize(
        mesh.vertices.astype(np.float32), mesh.faces.astype(np.uint32))
    mesh2 = trimesh.Trimesh(vertices=mesh.vertices[vm], faces=ft, process=False)
    labels2 = v_labels[vm]
    return mesh2, labels2, uv.astype(np.float64)


# --------------------------------------------------------------------------
# 6. Textures PBR procédurales (peinture 3D -> re-projection atlas)
# --------------------------------------------------------------------------

def _hex2rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float64) / 255.0


def _label_centroid(vertices, labels, lid):
    pts = vertices[labels == lid]
    if len(pts) == 0:
        return np.zeros(3)
    return pts.mean(0)


def make_material_fn(spec, vertices, labels, z_bounds):
    """Retourne eval(label, pos, wear) -> (rgb, roughness, metallic)."""
    pal = {m["id"]: m for m in spec["palette"]}
    ids = [m["id"] for m in spec["palette"]]
    rgb_of = {i: _hex2rgb(pal[i]["color"]) for i in pal}
    rough_of = {i: float(pal[i].get("roughness", 0.6)) for i in pal}
    metal_of = {i: float(pal[i].get("metallic", 0.0)) for i in pal}
    overlays = spec.get("overlays", [])
    zmin, zmax = z_bounds
    cents = {i: _label_centroid(vertices, labels, k)
             for k, i in enumerate(ids)}

    def eval_mat(lab, pos, wear):
        lab = np.asarray(lab)
        n = len(pos)
        col = np.zeros((n, 3))
        rough = np.zeros(n)
        metal = np.zeros(n)
        for k, i in enumerate(ids):
            m = lab == k
            if not m.any():
                continue
            col[m] = rgb_of[i]
            rough[m] = rough_of[i]
            metal[m] = metal_of[i]
        znorm = (pos[:, 2] - zmin) / max(1e-9, zmax - zmin)

        # micro-variations sur toutes les surfaces (vie le matériau uni)
        micro = fbm(pos[:, 0] * 7.0, pos[:, 1] * 7.0, pos[:, 2] * 7.0,
                    octaves=3, seed=17)
        col = col * (0.93 + 0.14 * micro)[:, None]

        for ov in overlays:
            kind = ov.get("type")
            tgt = ov.get("on")
            if kind == "rust" and tgt in ids:
                rust = rgb_of.get(ov.get("with", "r"), np.array([0.45, 0.24, 0.12]))
                m = lab == ids.index(tgt)
                band = ov.get("band", [0.0, 1.0])
                b = (_smoothstep(band[0] - 0.05, band[0] + 0.10, znorm)
                     * (1.0 - _smoothstep(band[1] - 0.10, band[1] + 0.05, znorm)))
                nse = fbm(pos[:, 0] * ov.get("scale", 6.0),
                          pos[:, 1] * ov.get("scale", 6.0),
                          pos[:, 2] * ov.get("scale", 6.0), octaves=4, seed=7)
                cov = float(ov.get("coverage", 0.35))
                t = np.clip((nse - (1.0 - 2.0 * cov))
                            / max(0.05, ov.get("softness", 0.18)), 0, 1)
                t = (t * b) * m
                col = col * (1 - t[:, None]) + rust[None, :] * t[:, None]
                rough = rough * (1 - t) + 0.88 * t
                metal = metal * (1 - t) + 0.15 * t
            elif kind == "wrap" and tgt in ids:
                m = lab == ids.index(tgt)
                if not m.any():
                    continue
                c = cents.get(tgt, np.zeros(3))
                theta = np.arctan2(pos[:, 1] - c[1], pos[:, 0] - c[0])
                u = theta / (2 * math.pi)
                count = float(ov.get("count", 8))
                twist = float(ov.get("twist", 0.3))
                ph = _frac(count * u + twist * znorm * count)
                bandm = (ph < 0.55).astype(np.float64)
                grain = fbm(pos[:, 0] * 40, pos[:, 1] * 40, pos[:, 2] * 40,
                            octaves=2, seed=31)
                tone = 1.0 - float(ov.get("darken", 0.45)) * bandm * (0.8 + 0.4 * grain)
                tone = np.where(m, tone, 1.0)
                col = col * tone[:, None]
                rough = np.where(m, np.clip(rough + 0.06 * grain, 0, 1), rough)
            elif kind == "edge_wear" and tgt in ids:
                m = lab == ids.index(tgt)
                amt = float(ov.get("amount", 0.5))
                nse = fbm(pos[:, 0] * ov.get("scale", 18.0),
                          pos[:, 1] * ov.get("scale", 18.0),
                          pos[:, 2] * ov.get("scale", 18.0), octaves=3, seed=53)
                t = np.clip(wear * (0.55 + 0.9 * nse) * amt * 2.2, 0, 1) * m
                col = col * (1 - t[:, None]) + (col * 1.3 + 0.06) * t[:, None]
                rough = rough * (1 - t) + (rough * 0.35) * t
                metal = metal + (0.95 - metal) * t * (metal > 0.4)

        return (np.clip(col, 0, 1),
                np.clip(rough, 0.04, 1),
                np.clip(metal, 0, 1))

    return eval_mat


def _rasterize_tri(uv_px, S):
    """Pixels couverts par un triangle UV -> (xs, ys, w0, w1, w2) vectorisé."""
    if not np.isfinite(uv_px).all():
        return None          # triangle dégénéré (UV NaN/inf d'xatlas)
    x0 = max(int(np.floor(uv_px[:, 0].min())), 0)
    x1 = min(int(np.ceil(uv_px[:, 0].max())), S - 1)
    y0 = max(int(np.floor(uv_px[:, 1].min())), 0)
    y1 = min(int(np.ceil(uv_px[:, 1].max())), S - 1)
    if x1 < x0 or y1 < y0:
        return None
    gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5,
                         np.arange(y0, y1 + 1) + 0.5)
    ax, ay = uv_px[0]
    bx, by = uv_px[1]
    cx, cy = uv_px[2]
    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(den) < 1e-12:
        return None
    w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
    w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
    w2 = 1.0 - w0 - w1
    m = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
    if not m.any():
        return None
    return gx[m].astype(np.int64), gy[m].astype(np.int64), w0[m], w1[m], w2[m]


def bake_textures(mesh, labels, uv, spec):
    """Peint l'atlas : albedo + metallicRoughness + normal. Retourne 3 PIL + wear."""
    S = int(spec.get("texture_size", 1024))
    albedo = np.zeros((S, S, 3), dtype=np.float64)
    rough_t = np.zeros((S, S), dtype=np.float64)
    metal_t = np.zeros((S, S), dtype=np.float64)
    filled = np.zeros((S, S), dtype=bool)

    faces = mesh.faces
    tri_uv = uv[faces] * S          # convention xatlas : origine en haut-gauche
    # -> ligne image = v * S directement, sans flip

    # usure des arêtes : défaut d'angle aux sommets (concavité/convexité locale)
    defects = np.abs(mesh.vertex_defects) if hasattr(mesh, "vertex_defects") \
        else np.zeros(len(mesh.vertices))
    wear_v = np.clip(defects / (np.percentile(defects, 95) + 1e-9), 0, 1)

    zmin, zmax = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
    eval_mat = make_material_fn(spec, mesh.vertices, labels, (zmin, zmax))

    for f in range(len(faces)):
        px = tri_uv[f]
        hit = _rasterize_tri(px, S)
        if hit is None:
            continue
        xs, ys, w0, w1, w2 = hit
        pos = (w0[:, None] * mesh.vertices[faces[f][0]]
               + w1[:, None] * mesh.vertices[faces[f][1]]
               + w2[:, None] * mesh.vertices[faces[f][2]])
        # étiquette du sommet dominant (au plus proche)
        w = np.stack([w0, w1, w2], 1)
        dom = labels[faces[f][w.argmax(1)]]
        wear = w0 * wear_v[faces[f][0]] + w1 * wear_v[faces[f][1]] \
            + w2 * wear_v[faces[f][2]]
        col, rough, metal = eval_mat(dom, pos, wear)
        albedo[ys, xs] = col
        rough_t[ys, xs] = rough
        metal_t[ys, xs] = metal
        filled[ys, xs] = True

    # dilatation : les texels vides des coutures héritent du voisin rempli
    if (~filled).any() and filled.any():
        ind = ndimage.distance_transform_edt(~filled, return_distances=False,
                                             return_indices=True)
        albedo = albedo[ind[0], ind[1]]
        rough_t = rough_t[ind[0], ind[1]]
        metal_t = metal_t[ind[0], ind[1]]

    albedo8 = (np.clip(albedo, 0, 1) * 255).astype(np.uint8)
    # normal map dérivée de la luminance (relief procédural gratuit)
    lum = albedo @ np.array([0.299, 0.587, 0.114])
    gx = ndimage.sobel(lum, 1) / 8.0
    gy = ndimage.sobel(lum, 0) / 8.0
    k = float(spec.get("normal_strength", 2.0))
    nx, ny = -gx * k, -gy * k
    nz = np.ones_like(nx)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    normal8 = (np.stack([nx / ln, ny / ln, nz / ln], -1) * 0.5 + 0.5) * 255
    normal8 = normal8.astype(np.uint8)
    # glTF : G = roughness, B = metallic
    mr8 = np.stack([255 * np.ones_like(rough_t), rough_t * 255, metal_t * 255],
                   -1).astype(np.uint8)

    return (Image.fromarray(albedo8),
            Image.fromarray(mr8),
            Image.fromarray(normal8),
            wear_v)


def attach_visual(mesh, uv, albedo_img, mr_img, normal_img):
    mat = trimesh.visual.material.PBRMaterial(
        name="forge_generated",
        baseColorFactor=[255, 255, 255, 255],
        baseColorTexture=albedo_img,
        metallicFactor=1.0,
        roughnessFactor=1.0,
        metallicRoughnessTexture=mr_img,
        normalTexture=normal_img,
        normalTextureScale=1.0,
    )
    mesh.visual = trimesh.visual.texture.TextureVisuals(
        uv=uv, image=albedo_img, material=mat)
    return mesh


# --------------------------------------------------------------------------
# 7. Cohérence : IoU des silhouettes re-projetées vs vues d'entrée
# --------------------------------------------------------------------------

def silhouette_iou(mesh, views_masks, grid_shape, size_m):
    """Re-projette le mesh final sur les 3 plans et mesure l'IoU."""
    from PIL import ImageDraw
    gx, gy, gz = grid_shape
    lo, hi = mesh.bounds
    ious = {}
    plan = {
        # (axe_u, axe_v, W, H, mask, flip_v)  flip si ligne 0 = +axe (z en haut)
        "front": (0, 2, gx, gz, views_masks[0], True),
        "side": (1, 2, gy, gz, views_masks[1], True),
        "top": (0, 1, gx, gy, views_masks[2], False),
    }
    for name, (ax_u, ax_v, Wg, Hg, mask_in, flip_v) in plan.items():
        H_in, W_in = mask_in.shape
        img = Image.new("L", (Wg, Hg), 0)
        d = ImageDraw.Draw(img)
        su, sv = (Wg - 1) / max(1e-9, hi[ax_u] - lo[ax_u]), \
                 (Hg - 1) / max(1e-9, hi[ax_v] - lo[ax_v])
        v = mesh.vertices
        for f in mesh.faces:
            pts = []
            for k in f:
                pu = (v[k][ax_u] - lo[ax_u]) * su
                pv_raw = (v[k][ax_v] - lo[ax_v]) * sv
                pv = (Hg - 1 - pv_raw) if flip_v else pv_raw
                pts.append((pu, pv))
            d.polygon(pts, fill=255)
        sil = np.asarray(img.resize((W_in, H_in), Image.LANCZOS)) > 96
        inter = (sil & mask_in).sum()
        union = (sil | mask_in).sum()
        ious[name] = round(inter / union, 4) if union else 0.0
    return ious


def save_view_maps(views, outdir, stem):
    """Sauvegarde les vues ASCII d'entrée en PNG (représentation interne)."""
    paths = []
    for name, rows in views.items():
        H, W = len(rows), max(len(r) for r in rows)
        im = Image.new("RGB", (W, H), (18, 16, 14))
        px = im.load()
        for r, line in enumerate(rows):
            for c, ch in enumerate(line):
                if ch not in EMPTY:
                    px[c, r] = (232, 100, 27) if ch == "#" else (216, 169, 58)
        scale = max(1, 256 // max(H, W))
        im = im.resize((W * scale, H * scale), Image.NEAREST)
        p = os.path.join(outdir, f"{stem}_view_{name}.png")
        im.save(p)
        paths.append(p)
    return paths


# --------------------------------------------------------------------------
# Pipeline complet
# --------------------------------------------------------------------------

def load_references(ref_path, outdir, stem):
    """Charge la fiche de références produite par research.py (recherche web).

    Copie la planche « détails à respecter » dans le dossier de sortie et
    retourne un résumé pour le rapport (checklist de QA). None si absent.
    """
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
             faces_all=False, references_path=None):
    t0 = time.time()
    os.makedirs(outdir, exist_ok=True)
    stem = spec.get("name", "objet")
    if res_override:
        spec["res"] = res_override
    if budget_override:
        spec["budget_tris"] = budget_override

    # 1-3 : vues -> volumes
    occ, zone, grid_shape, masks = build_volumes(spec)
    # 4 : géométrie
    mesh, v_labels = mesh_from_volumes(occ, zone, spec)
    # 5 : UV
    mesh, labels, uv = unwrap(mesh, v_labels)
    bad = ~np.isfinite(uv).all(axis=1)
    if bad.any():
        # coutures/ triangles dégénérés d'xatlas -> milieu d'atlas (jamais NaN)
        uv[bad] = 0.5
    # 6 : textures
    albedo_img, mr_img, normal_img, _ = bake_textures(mesh, labels, uv, spec)
    attach_visual(mesh, uv, albedo_img, mr_img, normal_img)
    trimesh.repair.fix_winding(mesh)

    # validations structurelles (mesh fusionné : xatlas duplique les sommets
    # de coutures UV -> faux négatif topologique sur le mesh texturé)
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

    # exports
    files = {}
    glb = os.path.join(outdir, stem + ".glb")
    trimesh.Scene(mesh).export(glb)
    files["glb"] = glb
    obj = os.path.join(outdir, stem + ".obj")
    try:
        mesh.export(obj, texture=albedo_img)
        if os.path.exists(obj):
            mtl = os.path.splitext(obj)[0] + ".mtl"
            if not os.path.exists(mtl):
                with open(mtl, "w") as fh:
                    fh.write(f"newmtl forge_generated\nKd 1 1 1\nmap_Kd {stem}.png\n")
            files["obj"] = obj
    except Exception as e:
        # échec d'export visible : jamais silencieux (bug qualité industrielle)
        print(f"  ⚠ export OBJ a échoué ({type(e).__name__}: {e}) "
              f"— le GLB/STL restent valides", file=sys.stderr)
    stl = os.path.join(outdir, stem + ".stl")
    solid.export(stl)
    files["stl"] = stl
    try:
        import usdz_export
        usd = os.path.join(outdir, stem + ".usdz")
        usdz_export.export_usdz(trimesh.Scene(solid), usd)
        files["usdz"] = usd
    except Exception as e:
        print(f"  ⚠ export USDZ a échoué ({type(e).__name__}: {e}) "
              f"— le GLB reste valide", file=sys.stderr)
    albedo_img.save(os.path.join(outdir, stem + "_albedo.png"))
    files["albedo"] = os.path.join(outdir, stem + "_albedo.png")

    # rendus de contrôle (albedo par sommet = aperçu texture)
    arr = np.asarray(albedo_img)
    h, w = arr.shape[:2]
    cols = np.clip((uv[:, 0] * (w - 1)).astype(int), 0, w - 1)
    rows = np.clip((uv[:, 1] * (h - 1)).astype(int), 0, h - 1)
    vcol = arr[rows, cols]
    # contraste léger : évite le rendu "lavé" sous 3 lumières
    vcol = np.clip((vcol.astype(np.float64) / 255.0) ** 1.18 * 0.9,
                   0, 1) * 255.0
    mesh_prev = mesh.copy()
    rgba = np.column_stack([vcol,
                            255 * np.ones((len(vcol), 1))]).astype(np.uint8)
    mesh_prev.visual = trimesh.visual.ColorVisuals(mesh_prev,
                                                   vertex_colors=rgba)
    scene = trimesh.Scene(mesh_prev)
    views_def = [("face", 0, 8), ("profil", 90, 8), ("trois_quarts", 42, 22),
                 ("dessus", 0, 78)]
    renders = []
    for label, az, el in views_def:
        img = renderer.render_view(scene, azimuth_deg=az, elevation_deg=el,
                                   size=768, ssaa=2)
        p = os.path.join(outdir, f"{stem}_{label}.png")
        img.save(p)
        renders.append(p)

    # vues ASCII internes (représentation)
    view_maps = save_view_maps(spec["views"], outdir, stem)

    # photos de TOUTES les faces + turntable (livraison complète)
    photos = {}
    if faces_all:
        face_paths, faces_sheet = renderer.render_all_faces(scene, outdir, stem,
                                                            size=768)
        turn_paths, turn_sheet = renderer.render_turntable(
            scene, outdir, stem, n=int(spec.get("turntable", 8)), size=560)
        photos = {"faces": face_paths, "all_faces": faces_sheet,
                  "turn_images": turn_paths, "turntable": turn_sheet}

    # références web (détails à respecter) → copie + checklist QA
    refs_summary = None
    ref_src = references_path or spec.get("references")
    if ref_src:
        refs_summary = load_references(ref_src, outdir, stem)

    report = {
        "pipeline": "meshgen v1 (visual hull multi-vues, type Meshy déterministe)",
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
    ap = argparse.ArgumentParser(description="Génération 3D multi-vues (zéro API)")
    ap.add_argument("spec", help="JSON de spec (vues ASCII + palette + overlays)")
    ap.add_argument("--out", required=True, help="répertoire de sortie")
    ap.add_argument("--res", type=int, default=None, help="résolution grille")
    ap.add_argument("--budget", type=int, default=None, help="budget triangles")
    ap.add_argument("--faces", choices=["all"], default=None,
                    help="all = photos des 6 faces + turntable (livraison Meshy)")
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
                      references_path=args.references)
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
