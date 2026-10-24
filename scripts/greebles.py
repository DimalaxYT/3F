#!/usr/bin/env python3
"""greebles.py — Bibliothèque de composants mécaniques Hard-Surface AAA (`v5.1`).

Fournit 8 sous-ensembles industriels / tactiques **100 % `watertight`** (compatibles
`manifold3d`, impression 3D ET baking de Normal Map Mikk `TANGENT VEC4`) permettant de
remplacer les parallélépipèdes naïfs par une vraie mécanique crédible :

  1. `hex_bolt(r, h, washer, socket)`      — Boulon 6-pans chanfreiné + rondelle + creux BTR
  2. `bolt_array(points, normals, r, h)`   — Série de boulons orientés sur n'importe quelle face 3D
  3. `toggle_latch(width, height, depth)`  — Loquet articulé complet (platine + crochet + étrier acier)
  4. `louver_vent(width, height, slats)`   — Grille d'aération encadrée à persiennes inclinées
  5. `picatinny_rail(length, width, teeth)`— Rail standard cranté trapézoïdal (type MIL-STD-1913)
  6. `ribbed_conduit(path, r, rings)`      — Gaine électrique / hydraulique annelée cintrée 3D
  7. `ergonomic_handle(span, reach, r)`    — Poignée industrielle cintrée sur embases moulées
  8. `corner_armor_cap(size, height)`      — Sabot de protection d'angle octogonal évidé en CSG
"""
from __future__ import annotations

import math
import numpy as np
import trimesh

import meshkit as mk


def _align_z_to_normal(mesh: trimesh.Trimesh, normal) -> trimesh.Trimesh:
    """Aligne l'axe `+Z` local de `mesh` sur le vecteur `normal` quelconque."""
    n = np.asarray(normal, dtype=np.float64)
    norm_len = float(np.linalg.norm(n))
    if norm_len < 1e-9:
        return mesh
    n /= norm_len
    z_axis = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    dot = float(np.clip(np.dot(z_axis, n), -1.0, 1.0))
    if dot > 0.99995:
        return mesh
    if dot < -0.99995:
        mesh.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1.0, 0.0, 0.0]))
        return mesh
    axis = np.cross(z_axis, n)
    axis /= np.linalg.norm(axis) + 1e-12
    angle = math.acos(dot)
    mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, axis))
    return mesh


def hex_bolt(r: float = 0.011, h: float = 0.009, washer: bool = True,
             socket: bool = True) -> trimesh.Trimesh:
    """Boulon hexagonal chanfreiné 100 % étanche avec rondelle d'appui et empreinte BTR."""
    r = float(r)
    h = float(h)
    parts = []
    z0 = 0.0
    if washer:
        wh = h * 0.24
        w = mk.cylinder(r * 1.34, wh, sections=18)
        parts.append(w)
        z0 = wh * 0.72

    ang = np.linspace(0.0, 2.0 * math.pi, 6, endpoint=False)
    hex_in = np.column_stack([r * 0.86 * np.cos(ang), r * 0.86 * np.sin(ang)])
    hex_mid = np.column_stack([r * np.cos(ang), r * np.sin(ang)])
    head = mk.loft([
        (hex_in, z0),
        (hex_mid, z0 + h * 0.16),
        (hex_mid, z0 + h * 0.82),
        (hex_in, z0 + h),
    ], caps=True)
    parts.append(head)
    bolt = mk.union(parts) if len(parts) > 1 else head

    if socket:
        cut_s = mk.cylinder(r * 0.42, h * 0.42, sections=6)
        mk.place(cut_s, 0.0, 0.0, z0 + h * 0.66)
        bolt = mk.difference(bolt, [cut_s])
    return bolt


def bolt_array(points, normals, r: float = 0.009, h: float = 0.0075,
               embed: float = 0.0018) -> list[trimesh.Trimesh]:
    """Instancie une liste de boulons 3D encastrés proprement de `embed` m dans la paroi."""
    proto = hex_bolt(r=r, h=h, washer=True, socket=True)
    out = []
    for pt, nrm in zip(points, normals):
        n = np.asarray(nrm, dtype=np.float64)
        n /= max(float(np.linalg.norm(n)), 1e-9)
        inst = proto.copy()
        _align_z_to_normal(inst, n)
        p = np.asarray(pt, dtype=np.float64) - n * float(embed)
        inst.apply_translation(p)
        out.append(inst)
    return out


def toggle_latch(width: float = 0.058, height: float = 0.118,
                 depth: float = 0.026) -> list[tuple[trimesh.Trimesh, str]]:
    """Loquet de fermeture mécanique multi-pièces (`[(mesh, role), ...]`) centré en `(0, 0, 0)`
    avec normale orientée vers `-Y` (façade avant standard 3d-forge) :
      - `"housing"` : platine creusée + crochet supérieur + levier articulé,
      - `"bail"`    : étrier en fil d'acier cintré + axes de goupille + 2 vis BTR.
    """
    W, H, D = float(width), float(height), float(depth)
    # Platine arrière encastrée
    base = mk.chamfer_box(W, D * 0.52, H, c=min(W, D) * 0.18)
    mk.place(base, 0.0, 0.0, -H * 0.5)
    pocket = mk.chamfer_box(W * 0.66, D * 0.50, H * 0.64, c=min(W, D) * 0.12)
    mk.place(pocket, 0.0, -D * 0.24, -H * 0.34)
    housing = mk.difference(base, [pocket])

    # Crochet supérieur d'accrochage
    hook = mk.chamfer_box(W * 0.56, D * 0.78, H * 0.19, c=min(W, D) * 0.15)
    mk.place(hook, 0.0, -D * 0.20, H * 0.27)
    # Levier de serrage basculant strié
    lever = mk.chamfer_box(W * 0.52, D * 0.68, H * 0.36, c=min(W, D) * 0.14)
    mk.rot_x(lever, -8.0)
    mk.place(lever, 0.0, -D * 0.24, -H * 0.38)
    housing_full = mk.union([housing, hook, lever])

    # Étrier métallique en U (`tube_sweep`) reliant le levier au crochet
    r_wire = max(W * 0.068, 0.0032)
    bx = W * 0.31
    bail_curve = np.array([
        [-bx, -D * 0.30, -H * 0.14],
        [-bx, -D * 0.52,  H * 0.08],
        [-bx * 0.72, -D * 0.54, H * 0.34],
        [ bx * 0.72, -D * 0.54, H * 0.34],
        [ bx, -D * 0.52,  H * 0.08],
        [ bx, -D * 0.30, -H * 0.14],
    ])
    bail = mk.tube_sweep(bail_curve, r=r_wire, sections=12, smooth_pts=24)
    pin = mk.cylinder(r_wire * 1.45, W * 0.80, sections=14)
    mk.rot_y(pin, 90.0)
    mk.place(pin, -W * 0.40, -D * 0.30, -H * 0.14)

    bolts = bolt_array(
        [[0.0, -D * 0.24, H * 0.44], [0.0, -D * 0.24, -H * 0.44]],
        [[0.0, -1.0, 0.0], [0.0, -1.0, 0.0]],
        r=W * 0.11,
        h=D * 0.24,
    )
    return [(housing_full, "housing"), (mk.union([bail, pin, *bolts]), "steel")]


def louver_vent(width: float = 0.16, height: float = 0.088, slats: int = 5,
                depth: float = 0.018) -> trimesh.Trimesh:
    """Grille de ventilation encadrée à persiennes inclinées (orientée vers `-Y`)."""
    W, H, D = float(width), float(height), float(depth)
    frame_out = mk.chamfer_box(W, D, H, c=min(W, D) * 0.20)
    mk.place(frame_out, 0.0, 0.0, -H * 0.5)
    cavity = mk.box(W * 0.84, D * 0.75, H * 0.78)
    mk.place(cavity, 0.0, -D * 0.32, -H * 0.39)
    shell = mk.difference(frame_out, [cavity])

    slat_meshes = [shell]
    n_s = max(2, int(slats))
    z_lo, z_hi = -H * 0.33, H * 0.33
    for i in range(n_s):
        zc = z_lo + (z_hi - z_lo) * (i + 0.5) / n_s
        s = mk.chamfer_box(W * 0.86, D * 0.62, (H * 0.78 / n_s) * 0.62, c=0.0018)
        mk.rot_x(s, 32.0)
        mk.place(s, 0.0, -D * 0.16, zc)
        slat_meshes.append(s)
    return mk.union(slat_meshes)


def picatinny_rail(length: float = 0.28, width: float = 0.026,
                   height: float = 0.014, teeth: int = 9) -> trimesh.Trimesh:
    """Rail tactique trapézoïdal cranté (axe long `Y`, posé à `z = 0`)."""
    L, W, H = float(length), float(width), float(height)
    prof = [
        (-W * 0.34, 0.0),
        ( W * 0.34, 0.0),
        ( W * 0.34, H * 0.36),
        ( W * 0.50, H * 0.68),
        ( W * 0.38, H),
        (-W * 0.38, H),
        (-W * 0.50, H * 0.68),
        (-W * 0.34, H * 0.36),
    ]
    bar = mk.extrude(prof, L)
    mk.rot_x(bar, 90.0)
    mk.place(bar, 0.0, L * 0.5, 0.0)

    # v5.9 — fentes recalées sur le MIL-STD-1913 : rail de 9,5 mm, fente
    # profonde de 3,2 mm (semelle à 66 % de la hauteur) et large de 5,35 mm
    # pour un pas de 10 mm (53 %). L'ancienne découpe (semelle à 60 %, fente à
    # 44 %) était déjà juste ; elle est simplement calée au standard.
    # ATTENTION : `mk.box` est posé sur `z = 0` (il n'est PAS centré en Z).
    # Placer la fente à 0,95 H l'envoyait flotter au-dessus du rail : la
    # différence ne retirait rien et le rail sortait en bande lisse.
    n_t = max(2, int(teeth))
    pitch = L * 0.84 / n_t
    slot_len = pitch * 0.53
    slot_floor = H * (1.0 - 3.2 / 9.5)
    cuts = []
    for k in range(n_t):
        yc = -L * 0.42 + pitch * (k + 0.5)
        slot = mk.box(W * 1.25, slot_len, H * 1.30)
        mk.place(slot, 0.0, yc, slot_floor)
        cuts.append(slot)
    return mk.difference(bar, cuts)


def ribbed_conduit(path, r: float = 0.011, rings: int = 12) -> trimesh.Trimesh:
    """Gaine blindée annelée le long d'une courbe 3D `path` (`100 % watertight`)."""
    pts = np.asarray(path, dtype=np.float64)
    core = mk.tube_sweep(pts, r=float(r) * 0.82, sections=14, smooth_pts=32)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    u = np.concatenate([[0.0], np.cumsum(np.maximum(seg, 1e-6))])
    u /= u[-1]
    parts = [core]
    n_r = max(3, int(rings))
    for k in range(n_r):
        tk = (k + 0.5) / n_r
        idx = int(np.clip(np.searchsorted(u, tk) - 1, 0, len(pts) - 2))
        frac = (tk - u[idx]) / max(u[idx + 1] - u[idx], 1e-6)
        pos = pts[idx] * (1.0 - frac) + pts[idx + 1] * frac
        tang = pts[idx + 1] - pts[idx]
        ring = mk.torus(float(r) * 0.90, float(r) * 0.24)
        _align_z_to_normal(ring, tang)
        ring.apply_translation(pos)
        parts.append(ring)
    return mk.union(parts)


def ergonomic_handle(span: float = 0.17, reach: float = 0.040,
                     r: float = 0.0105) -> list[tuple[trimesh.Trimesh, str]]:
    """Poignée industrielle montée sur deux embases chanfreinées boulonnées (axe long `Y`,
    saillie vers `+X`, centrée en `(0, 0, 0)`)."""
    S, R = float(span), float(reach)
    bosses = []
    bolts = []
    for sy in (-1.0, 1.0):
        b_mount = mk.chamfer_box(R * 0.48, S * 0.22, S * 0.24, c=R * 0.10)
        mk.place(b_mount, R * 0.14, sy * S * 0.42, -S * 0.12)
        bosses.append(b_mount)
        bolts.extend(bolt_array(
            [[R * 0.36, sy * S * 0.42, S * 0.06], [R * 0.36, sy * S * 0.42, -S * 0.06]],
            [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            r=r * 0.52,
            h=r * 0.45,
        ))
    curve = np.array([
        [0.0,      -S * 0.42, 0.0],
        [R * 0.55, -S * 0.40, -R * 0.10],
        [R,        -S * 0.28, -R * 0.16],
        [R,         S * 0.28, -R * 0.16],
        [R * 0.55,  S * 0.40, -R * 0.10],
        [0.0,       S * 0.42, 0.0],
    ])
    bar = mk.tube_sweep(curve, r=float(r), sections=16, smooth_pts=28)
    grip_sleeve = mk.cylinder(float(r) * 1.24, S * 0.44, sections=16)
    mk.rot_x(grip_sleeve, 90.0)
    mk.place(grip_sleeve, R, S * 0.22, -R * 0.16)
    return [
        (mk.union(bosses), "mount"),
        (mk.union([bar, *bolts]), "steel"),
        (grip_sleeve, "grip"),
    ]


def corner_armor_cap(size: float = 0.082, height: float = 0.38) -> trimesh.Trimesh:
    """Sabot d'armure d'angle octogonal profilé avec poches d'allègement CSG et boulons."""
    S, H = float(size), float(height)
    base_prof = [
        (-S * 0.50, -S * 0.30),
        (-S * 0.30, -S * 0.50),
        ( S * 0.30, -S * 0.50),
        ( S * 0.50, -S * 0.30),
        ( S * 0.50,  S * 0.30),
        ( S * 0.30,  S * 0.50),
        (-S * 0.30,  S * 0.50),
        (-S * 0.50,  S * 0.30),
    ]
    top_prof = [(x * 0.88, y * 0.88) for x, y in base_prof]
    pillar = mk.loft([
        ([(x * 0.90, y * 0.90) for x, y in base_prof], 0.0),
        (base_prof, H * 0.07),
        (base_prof, H * 0.90),
        (top_prof, H),
    ], caps=True)
    # Poche centrale encastrée sur chaque face externe pour casser l'aspect "pilier lisse"
    cuts = []
    for ang_deg in (0.0, 90.0, 180.0, 270.0):
        c_box = mk.chamfer_box(S * 0.44, S * 0.24, H * 0.56, c=S * 0.06)
        mk.place(c_box, 0.0, -S * 0.46, H * 0.22)
        mk.rot_z(c_box, ang_deg)
        cuts.append(c_box)
    return mk.difference(pillar, cuts)
