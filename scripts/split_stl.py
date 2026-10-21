#!/usr/bin/env python3
"""split_stl.py — Découpe automatique d'objets 3D de grande taille pour
imprimantes 3D réelles (ex. plateau Bambu Lab 256×256×256 mm ou Prusa 220×220×250 mm)
avec **tenons et mortaises d'assemblage chanfreinés** et jeu mécanique paramétrique.

Pourquoi ce script est crucial :
  Un katana d'1,00 m ou une épée de 0,96 m est étanche (`watertight=True`), mais
  impossible à imprimer d'un bloc à l'échelle 1:1. `split_stl.py` :
    1. Détecte récursivement tout axe dépassant le volume d'impression (`--bed`),
    2. Coupe proprement en demi-espaces booléens exacts `manifold3d`,
    3. Génère sur chaque plan de coupe 1 ou 2 **tenons mâles chanfreinés** d'un côté
       et les **mortaises femelles avec jeu d'assemblage (`--clearance 0.0002` = 0,20 mm)**
       de l'autre, dimensionnés automatiquement à la section réelle de la pièce !
    4. Pose chaque tronçon à plat (`z = 0`), vérifie `is_watertight == True` et le
       respect strict du volume plateau, puis rend une vue éclatée `exploded_preview.png`.

CLI :
    python scripts/split_stl.py examples/katana/katana.stl -o out/katana_print --bed 0.256 0.256 0.256
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import meshkit as mk
import renderer
import validate as valmod


def _make_aligned_pin(center_3d: np.ndarray, axis: int, radius: float,
                      depth: float, clearance: float = 0.0) -> trimesh.Trimesh:
    """Crée un tenon tronconique chanfreiné centré sur le plan de coupe `center_3d`
    le long de `axis` (`0=X, 1=Y, 2=Z`), facile à insérer sans support."""
    r = max(1.2e-3, float(radius) + float(clearance))
    h = max(3.0e-3, float(depth) + 2.0 * abs(float(clearance)))
    pin = mk.frustum(r, r * 0.84, h, sections=20)
    pin.apply_translation([0.0, 0.0, -h * 0.5])
    if axis == 0:
        mk.rot_y(pin, 90.0)
    elif axis == 1:
        mk.rot_x(pin, -90.0)
    pin.apply_translation(center_3d)
    return pin


def _slice_once_with_pins(mesh: trimesh.Trimesh, axis: int, cut_val: float,
                          clearance: float = 0.0002,
                          pin_depth: float = 0.010) -> tuple[trimesh.Trimesh, trimesh.Trimesh, int]:
    """Coupe `mesh` sur `coord[axis] = cut_val` avec tenon(s) + mortaise(s) auto-calibrés."""
    lo, hi = mesh.bounds
    span = hi - lo
    big = float(span.max()) * 4.0 + 0.5

    # Boîtes demi-espaces exactes
    c_lo = 0.5 * (lo + hi)
    c_hi = 0.5 * (lo + hi)
    dims = np.full(3, big, dtype=float)
    dims[axis] = big
    c_lo[axis] = cut_val - big * 0.5
    c_hi[axis] = cut_val + big * 0.5

    box_lo = mk.box(*dims)
    box_lo.apply_translation([c_lo[0], c_lo[1], c_lo[2] - big * 0.5])
    box_hi = mk.box(*dims)
    box_hi.apply_translation([c_hi[0], c_hi[1], c_hi[2] - big * 0.5])

    part_a = mk.intersection(mesh, box_lo)
    part_b = mk.intersection(mesh, box_hi)

    # Analyse la section réelle au niveau de la coupe pour calibrer le(s) tenon(s)
    normal = np.zeros(3)
    normal[axis] = 1.0
    origin = 0.5 * (lo + hi)
    origin[axis] = cut_val
    sec = mesh.section(plane_origin=origin, plane_normal=normal)

    n_pins = 0
    if sec is not None:
        pts_3d = sec.vertices
        if len(pts_3d) >= 4:
            other = [k for k in range(3) if k != axis]
            ext_2d = pts_3d[:, other].max(0) - pts_3d[:, other].min(0)
            min_w = float(ext_2d.min())
            max_w = float(ext_2d.max())
            centroid = pts_3d.mean(0)
            centroid[axis] = cut_val
            # Rayon de tenon sûr = 22% de l'épaisseur minimale de la lame/pièce (borné [1.4mm .. 6mm])
            r_pin = float(np.clip(min_w * 0.22, 0.0014, 0.0060))
            if min_w >= 0.0042:
                pin_centers = [centroid]
                if max_w > 4.0 * min_w and max_w >= 0.028:
                    long_ax = other[int(np.argmax(ext_2d))]
                    off = np.zeros(3)
                    off[long_ax] = max_w * 0.24
                    pin_centers = [centroid - off, centroid + off]

                male_pins = [_make_aligned_pin(c, axis, r_pin, pin_depth, clearance=0.0)
                             for c in pin_centers]
                female_holes = [_make_aligned_pin(c, axis, r_pin, pin_depth + 0.0008,
                                                  clearance=clearance)
                                for c in pin_centers]
                try:
                    cand_a = mk.union([part_a] + male_pins)
                    cand_b = mk.difference(part_b, female_holes)
                    if cand_a.is_watertight and cand_b.is_watertight:
                        part_a, part_b = cand_a, cand_b
                        n_pins = len(pin_centers)
                except Exception:
                    pass

    return part_a, part_b, n_pins


def split_to_bed(mesh: trimesh.Trimesh, bed=(0.256, 0.256, 0.256),
                 clearance: float = 0.0002, pin_depth: float = 0.010) -> tuple[list[trimesh.Trimesh], int]:
    """Découpe récursivement `mesh` jusqu'à ce que chaque pièce tienne dans `bed`
    (marge de sécurité de `2 * pin_depth` incluse pour les tenons mâles)."""
    bed_arr = np.asarray(bed, dtype=float)
    safe_bed = np.maximum(bed_arr - 2.2 * pin_depth, bed_arr * 0.75)
    total_pins = 0

    queue = [mesh.copy()]
    finished: list[trimesh.Trimesh] = []
    guard = 0
    while queue and guard < 64:
        guard += 1
        cur = queue.pop(0)
        lo, hi = cur.bounds
        dims = hi - lo
        # Teste si la pièce tient déjà dans le plateau (quitte à la coucher à 90° !)
        if np.all(np.sort(dims) <= np.sort(bed_arr) + 1e-6):
            finished.append(cur)
            continue
        ax = int(np.argmax(dims / safe_bed))
        n_segs = max(2, int(math.ceil(dims[ax] / safe_bed[ax])))
        cut_pos = float(lo[ax] + dims[ax] / n_segs)
        pa, pb, npin = _slice_once_with_pins(cur, ax, cut_pos,
                                             clearance=clearance, pin_depth=pin_depth)
        total_pins += npin
        queue.insert(0, pb)
        queue.insert(0, pa)

    return finished, total_pins


def orient_for_print(part: trimesh.Trimesh, bed=(0.256, 0.256, 0.256)) -> trimesh.Trimesh:
    """Oriente la pièce pour tenir dans `(bx, by, bz)` et la pose à `z = 0`."""
    m = part.copy()
    bed_arr = np.asarray(bed, dtype=float)
    for rx, ry in ((0, 0), (90, 0), (0, 90), (90, 90)):
        cand = m.copy()
        if rx:
            mk.rot_x(cand, rx)
        if ry:
            mk.rot_y(cand, ry)
        mk.ground(cand)
        dims = cand.bounds[1] - cand.bounds[0]
        if np.all(dims <= bed_arr + 1e-5):
            return cand
    mk.ground(m)
    return m


def export_split_kit(stl_path: str, outdir: str, bed=(0.256, 0.256, 0.256),
                     clearance: float = 0.0002, pin_depth: float = 0.010) -> dict:
    os.makedirs(outdir, exist_ok=True)
    src = trimesh.load(stl_path, force="mesh")
    parts_world, total_pins = split_to_bed(src, bed=bed, clearance=clearance,
                                           pin_depth=pin_depth)

    # Rend une vue éclatée 3D montrant clairement les pièces et leurs tenons d'assemblage !
    exp_scene = trimesh.Scene()
    palette = ("#e06a2b", "#d8dde4", "#e2b24a", "#5aa2d8", "#6ac48a", "#c974d8")
    centers = [p.bounds.mean(0) for p in parts_world]
    global_c = np.mean(centers, axis=0)
    for i, pw in enumerate(parts_world):
        exploded = pw.copy()
        offset_dir = pw.bounds.mean(0) - global_c
        exploded.apply_translation(offset_dir * 0.28)
        exploded.visual = trimesh.visual.TextureVisuals(
            material=mk.mat.abs_injected(palette[i % len(palette)], roughness=0.30).to_pbr()
        )
        exp_scene.add_geometry(exploded, geom_name=f"segment_{i + 1:02d}")

    preview_png = os.path.join(outdir, "exploded_preview.png")
    renderer.render_view(exp_scene, azimuth_deg=52.0, elevation_deg=24.0, size=900).save(preview_png)

    exported = []
    for i, pw in enumerate(parts_world):
        oriented = orient_for_print(pw, bed=bed)
        p_out = os.path.join(outdir, f"part_{i + 1:02d}.stl")
        oriented.export(p_out)
        chk = valmod.check_mesh(oriented)
        dims = (oriented.bounds[1] - oriented.bounds[0]).round(4).tolist()
        exported.append({
            "index": i + 1,
            "path": os.path.abspath(p_out),
            "dims_m": dims,
            "watertight": bool(chk["watertight"]),
            "fits_bed": bool(all(d <= b + 1e-4 for d, b in zip(dims, bed))),
            "triangles": int(len(oriented.faces)),
        })

    manifest = {
        "source": os.path.abspath(stl_path),
        "bed_m": list(bed),
        "clearance_mm": round(clearance * 1000.0, 3),
        "n_parts": len(exported),
        "alignment_pins": int(total_pins),
        "all_watertight": all(e["watertight"] for e in exported),
        "all_fit_bed": all(e["fits_bed"] for e in exported),
        "exploded_preview": os.path.abspath(preview_png),
        "parts": exported,
    }
    with open(os.path.join(outdir, "split_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stl", help="Fichier .stl ou .glb étanche à découper")
    ap.add_argument("-o", "--outdir", required=True)
    ap.add_argument("--bed", nargs=3, type=float, default=[0.256, 0.256, 0.256],
                    metavar=("BX", "BY", "BZ"), help="Volume imprimante en mètres (défaut Bambu 256mm)")
    ap.add_argument("--clearance", type=float, default=0.0002,
                    help="Jeu mécanique tenon/mortaise en mètres (défaut 0.0002 = 0.20 mm)")
    args = ap.parse_args()
    res = export_split_kit(args.stl, args.outdir, bed=tuple(args.bed),
                           clearance=args.clearance)
    print(json.dumps({k: v for k, v in res.items() if k != "parts"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
