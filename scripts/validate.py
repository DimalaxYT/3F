#!/usr/bin/env python3
"""
validate.py — contrôle qualité d'un mesh (GLB / OBJ / STL / PLY).

Vérifie : étanchéité (watertight), orientation des faces, volume positif,
composants connexes, faces dégénérées / dupliquées, dimensions, budget poly.
    python validate.py fichier.glb [--json] [--max-tris 200000]
"""
from __future__ import annotations
import argparse
import json
import sys

import numpy as np
import trimesh


def check_mesh(mesh_or_scene, max_tris=200000) -> dict:
    if isinstance(mesh_or_scene, trimesh.Scene):
        parts = [g for g in mesh_or_scene.geometry.values()
                 if isinstance(g, trimesh.Trimesh) and len(g.faces)]
        if not parts:
            raise ValueError("scène sans mesh")
        merged = trimesh.util.concatenate(parts)
    else:
        merged = mesh_or_scene

    tris = int(len(merged.faces))
    area = merged.area_faces
    degenerate = int((area < 1e-14).sum())
    unique_faces = np.unique(np.sort(merged.faces, axis=1), axis=0)
    duplicates = int(tris - len(unique_faces))
    watertight = bool(merged.is_watertight)
    winding = bool(merged.is_winding_consistent)
    volume = float(abs(merged.volume)) if watertight else float("nan")
    body_count = int(merged.body_count) if watertight else -1
    dims = merged.extents.tolist()

    hard_fail = (not watertight) or (watertight and merged.volume <= 0)
    return {
        "watertight": watertight,
        "winding_consistent": winding,
        "volume_m3": round(volume, 9) if watertight else None,
        "volume_liters": round(volume * 1000, 3) if watertight else None,
        "dims_m": [round(d, 4) for d in dims],
        "triangles": tris,
        "vertices": int(len(merged.vertices)),
        "components": body_count,
        "degenerate_faces": degenerate,
        "duplicate_faces": duplicates,
        "over_budget": tris > max_tris,
        "is_printable": bool(watertight and winding and (not watertight or volume > 0)),
        "hard_fail": bool(hard_fail),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validation de mesh 3D")
    ap.add_argument("file", help="fichier .glb/.obj/.stl/.ply")
    ap.add_argument("--json", action="store_true", help="sortie JSON brute")
    ap.add_argument("--max-tris", type=int, default=200000)
    args = ap.parse_args(argv)

    mesh = trimesh.load(args.file, force="scene" if args.file.lower().endswith((".glb", ".gltf")) else None)
    try:
        checks = check_mesh(mesh, max_tris=args.max_tris)
    except ValueError as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(checks, indent=2))
    else:
        wt = "✓ étanche" if checks["watertight"] else "✗ NON ÉTANCHE"
        print(f"{args.file}")
        print(f"  étanchéité      : {wt}")
        print(f"  orientation     : {'✓ cohérente' if checks['winding_consistent'] else '✗ incohérente'}")
        if checks["volume_liters"] is not None:
            print(f"  volume          : {checks['volume_liters']} L "
                  f"({checks['volume_m3'] * 1e9:.0f} mm³)")
        print(f"  dimensions (m)  : {checks['dims_m']}")
        print(f"  triangles       : {checks['triangles']} "
              f"({'dans le budget' if not checks['over_budget'] else 'HORS BUDGET'})")
        print(f"  dégénérées/dupl.: {checks['degenerate_faces']} / {checks['duplicate_faces']}")
        print(f"  impression 3D   : {'✓ prête' if checks['is_printable'] else '✗ à retravailler'}")
    return 1 if checks["hard_fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
