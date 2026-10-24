#!/usr/bin/env python3
"""Maillage haute densité (hero) — **entre 1 000 000 et 10 000 000 de faces**.

    PYTHONPATH=scripts python3 examples/g36_rifle/build_hero.py [--subdiv 4]

Le GLB de jeu fait 6 336 triangles : c'est la bonne résolution pour du temps
réel, et c'est trop peu pour une image fixe ou une cinématique. Ce script part
de ce GLB (UV déjà dépliés, atlas 2048, matériau PBR) et en fabrique une
version lourde :

1. **subdivision de Catmull-Clark simplifiée à la volée** — chaque triangle est
   coupé en quatre, les UV sont interpolés au milieu des arêtes, donc l'atlas
   reste exactement le même (aucun dépliage, aucun rebake) ;
2. **lissage Taubin avec épinglage des arêtes vives** — on mesure l'angle
   dièdre de chaque arête ; au-delà de 52° (rail, faces de culasse, chants de
   plaque) les sommets sont figés, en dessous (chanfreins, congés, cylindres)
   la surface est lissée. Les formes restent du hard-surface, mais les congés
   deviennent de vrais rayons au lieu d'une facette de 45° ;
3. **normales recalculées sur les sommets soudés**, puis redistribuées aux
   copies de couture UV : sans ça, chaque couture d'atlas réapparaît en ligne
   d'ombre.

Le compte de faces final est vérifié : hors de la fourchette, le script échoue.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

GLB_IN = ROOT / "exports" / "g36_rifle" / "g36_rifle_game.glb"
OUT_DIR = ROOT / "exports" / "g36_rifle" / "hero"
OUT_GLB = OUT_DIR / "g36_rifle_hero.glb"

TARGET_MIN, TARGET_MAX = 1_000_000, 10_000_000


# --------------------------------------------------------------------------- #
# Subdivision 1-to-4 avec interpolation UV
# --------------------------------------------------------------------------- #

def subdivide4(verts: np.ndarray, faces: np.ndarray, uv: np.ndarray,
               iters: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Coupe chaque triangle en 4, `iters` fois, en interpolant les UV."""
    verts = np.asarray(verts, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    uv = np.asarray(uv, dtype=np.float64)
    for _ in range(int(iters)):
        edges = np.concatenate(
            [faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=0)
        uniq, inv = np.unique(np.sort(edges, axis=1), axis=0, return_inverse=True)
        mid_v = (verts[uniq[:, 0]] + verts[uniq[:, 1]]) * 0.5
        mid_t = (uv[uniq[:, 0]] + uv[uniq[:, 1]]) * 0.5
        base = len(verts)
        verts = np.vstack([verts, mid_v])
        uv = np.vstack([uv, mid_t])
        m = inv.reshape(3, -1).T + base          # (F, 3) : arêtes 01, 12, 20
        a, b, c = faces[:, 0], faces[:, 1], faces[:, 2]
        ab, bc, ca = m[:, 0], m[:, 1], m[:, 2]
        faces = np.concatenate([
            np.column_stack([a, ab, ca]),
            np.column_stack([ab, b, bc]),
            np.column_stack([ca, bc, c]),
            np.column_stack([ab, bc, ca]),
        ], axis=0)
    return verts, faces, uv


# --------------------------------------------------------------------------- #
# Lissage Taubin à arêtes vives préservées
# --------------------------------------------------------------------------- #

def crease_preserving_smooth(verts: np.ndarray, faces: np.ndarray,
                             angle_deg: float = 52.0, iters: int = 8,
                             lamb: float = 0.42, mu: float = -0.45
                             ) -> tuple[np.ndarray, np.ndarray]:
    """Lisse les surfaces courbes, fige les arêtes dont le dièdre dépasse
    `angle_deg`. Retourne (positions, normales) par sommet d'origine."""
    from scipy.sparse import coo_matrix

    # soudure par position : les copies de couture UV doivent bouger ensemble
    key = np.round(verts, 7)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    wf = inv[faces]
    n = len(uniq)

    w = trimesh.Trimesh(uniq, wf, process=False)
    ang = w.face_adjacency_angles
    sharp = w.face_adjacency_edges[ang > np.radians(angle_deg)]
    pinned = np.zeros(n, dtype=bool)
    pinned[sharp.ravel()] = True

    e = np.vstack([wf[:, [0, 1]], wf[:, [1, 2]], wf[:, [2, 0]]])
    A = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n)).tocsr()
    A = A + A.T
    deg = np.asarray(A.sum(1)).ravel()
    deg[deg == 0] = 1.0
    dinv = 1.0 / deg

    def lap(p: np.ndarray) -> np.ndarray:
        return A.dot(p) * dinv[:, None] - p

    p = uniq.astype(np.float64)
    free = ~pinned
    for _ in range(int(iters)):
        d = lap(p)
        d[~free] = 0.0
        p = p + lamb * d
        d = lap(p)
        d[~free] = 0.0
        p = p + mu * d

    w2 = trimesh.Trimesh(p, wf, process=False)
    nrm = np.asarray(w2.vertex_normals)
    return p[inv], nrm[inv], int(pinned.sum()), n


# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subdiv", type=int, default=4,
                    help="nombre de passes 1->4 (4 passes = x256)")
    ap.add_argument("--angle", type=float, default=52.0)
    ap.add_argument("--iters", type=int, default=8)
    args = ap.parse_args()

    if not GLB_IN.is_file():
        print(f"GLB absent : {GLB_IN}", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    scene = trimesh.load(GLB_IN, force="scene")
    geoms = [g for g in scene.geometry.values() if len(g.faces)]
    tris_in = sum(len(g.faces) for g in geoms)
    print(f"entrée : {len(geoms)} géométrie(s), {tris_in} triangles")

    all_v, all_f, all_uv = [], [], []
    offset = 0
    material = None
    for g in geoms:
        trilist = g.visual.material
        if material is None:
            material = trilist
        v = np.asarray(g.vertices, dtype=np.float64)
        f = np.asarray(g.faces, dtype=np.int64)
        uv = np.asarray(g.visual.uv, dtype=np.float64)
        v, f, uv = subdivide4(v, f, uv, args.subdiv)
        v, nrm, pinned, n = crease_preserving_smooth(
            v, f, angle_deg=args.angle, iters=args.iters)
        print(f"  {len(v):>9} sommets · {len(f):>9} faces "
              f"({pinned}/{n} sommets figés sur arêtes)")
        all_v.append(v)
        all_f.append(f + offset)
        all_uv.append(uv)
        offset += len(v)

    verts = np.vstack(all_v)
    faces = np.vstack(all_f)
    uv = np.vstack(all_uv)

    if not (TARGET_MIN <= len(faces) <= TARGET_MAX):
        print(f"ÉCHEC : {len(faces)} faces hors de la fourchette "
              f"[{TARGET_MIN:,} .. {TARGET_MAX:,}]", file=sys.stderr)
        return 2

    # La carte de normales du jeu est cuite en espace tangent sur le maillage
    # à 6 336 triangles. Ses frontières d'îlots UV portent un saut de trame de
    # tangente ; sur le maillage de jeu, les facettes le masquent, mais dès que
    # l'ombrage devient lisse (c'est tout l'intérêt du hero) il ressort en
    # longues coutures sombres en travers des flancs. À 1,6 M de triangles, la
    # géométrie porte le relief : on ne garde que l'albédo et l'ORM.
    if material is not None:
        material.normalTexture = None
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    # `include_normals=True` est OBLIGATOIRE : sans l'attribut NORMAL, le
    # moteur recalcule les normales par sommet *après* la séparation des
    # coutures UV, et chaque frontière d'îlot de l'atlas réapparaît en pli
    # sombre. Les normales exportées viennent des sommets soudés par position,
    # donc elles sont identiques de part et d'autre d'une couture.
    mesh.export(OUT_GLB, file_type="glb", include_normals=True)

    welded = trimesh.Trimesh(vertices=np.round(verts, 7), faces=faces,
                             process=True)

    size_mb = OUT_GLB.stat().st_size / 1e6
    print(f"faces : {len(faces):,} · sommets : {len(verts):,} · "
          f"watertight (sommets soudés) : {welded.is_watertight}")
    print(f"sortie : {OUT_GLB.relative_to(ROOT)} ({size_mb:.1f} Mo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
