"""
build_yz125.py — Yamaha YZ125 Factory Works 2-Temps (Édition Intégrale v4.1 — Persistante `exports/yamaha_yz125/`).

Génère un modèle 3D 100 % procédural sur mesure (aucun catalogue `recipes/*`) :
  - 2 roues motocross complètes 21" / 19" à 32 rayons inox croisés + écrous chromés + moyeux CNC Bleus + disques Wave,
  - Cinématique hiérarchique réelle (`front_steering -> front_wheel`) sans faux-rond ni désalignement,
  - Châssis Yamaha Deltabox hydroformé caissonné (`mk.sweep`) + bras oscillant caissonné effilé + Pro-Link + boucle carrée,
  - Moteur 125 cc 2-temps liquide YPVS plein volume (zéro vide dans le cadre), culasse VHM Or, Keihin PWK38, pot Works.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
import trimesh

ROOT = Path(__file__).resolve().parents[2]
for _p in ("scripts", str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import meshkit as mk
import organic as org

_BOX_PROF = [
    (-0.50, -0.34),
    (-0.34, -0.50),
    (+0.34, -0.50),
    (+0.50, -0.34),
    (+0.50, +0.34),
    (+0.34, +0.50),
    (-0.34, +0.50),
    (-0.50, +0.34),
]


def _box_beam(
    pts: list[tuple[float, float, float]],
    scales: list[tuple[float, float]] | tuple[float, float],
    smooth_pts: int = 24,
) -> trimesh.Trimesh:
    """Poutre aluminium hydroformée / caissonnée à section rectangulaire chanfreinée évolutive."""
    from scipy.interpolate import PchipInterpolator

    arr = np.asarray(pts, dtype=np.float64)
    if len(arr) >= 3 and smooth_pts > len(arr):
        t_in = np.linspace(0.0, 1.0, len(arr))
        t_ev = np.linspace(0.0, 1.0, smooth_pts)
        path_s = np.column_stack([PchipInterpolator(t_in, arr[:, k])(t_ev) for k in range(3)])
        if isinstance(scales, (list, tuple)) and len(scales) == len(arr) and isinstance(scales[0], (list, tuple)):
            sc_arr = np.asarray(scales, dtype=np.float64)
            sc_s = [
                (float(PchipInterpolator(t_in, sc_arr[:, 0])(te)), float(PchipInterpolator(t_in, sc_arr[:, 1])(te)))
                for te in t_ev
            ]
        else:
            sc_s = scales
        m = mk.sweep(_BOX_PROF, path_s, scale=sc_s, up_hint=(1.0, 0.0, 0.0), caps=True)
    else:
        m = mk.sweep(_BOX_PROF, arr, scale=scales, up_hint=(1.0, 0.0, 0.0), caps=True)
    if float(m.volume) < 0.0:
        m.invert()
    return m


def _procedural_micro_tile(kind: str, size: int = 256) -> np.ndarray:
    """Génère un champ de micro-grain déterministe si la tuile PNG n'est pas présente sur disque."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) / float(size)
    tau = 2.0 * math.pi
    if kind == "alu":
        g = 0.65 * np.sin(tau * (yy * 46.0 + 0.04 * np.sin(tau * xx * 3.0))) + 0.35 * np.sin(tau * yy * 113.0)
    elif kind == "rubber":
        g = np.sin(tau * xx * 29.0) * np.cos(tau * yy * 31.0) + 0.5 * np.sin(tau * (xx * 61.0 + yy * 57.0))
    else:
        g = 0.5 * np.sin(tau * xx * 19.0) * np.sin(tau * yy * 23.0)
    g = g - g.mean()
    return np.clip(g / (float(g.std()) * 2.2 + 1e-6), -1.0, 1.0)


def _load_gpu_relief(img_path: Path, fallback_kind: str) -> np.ndarray:
    if img_path.is_file():
        arr = np.asarray(Image.open(img_path).convert("L"), dtype=np.float32) / 255.0
        arr = arr - arr.mean()
        std = float(arr.std())
        if std > 1e-5:
            return np.clip(arr / (2.5 * std), -1.0, 1.0)
    return _procedural_micro_tile(fallback_kind)


def _apply_gpu_micro_grain(mesh: trimesh.Trimesh, relief: np.ndarray | None, amp_m: float = 0.00045, scale: float = 6.0) -> None:
    if relief is None or len(mesh.vertices) < 24:
        return
    h, w = relief.shape
    v = np.asarray(mesh.vertices, dtype=np.float64)
    nrm = np.asarray(mesh.vertex_normals, dtype=np.float64)
    u = np.mod((v[:, 1] + 0.35 * v[:, 0]) * scale, 1.0) * (w - 1)
    vv = np.mod((v[:, 2] - 0.25 * v[:, 0]) * scale, 1.0) * (h - 1)
    iu = np.clip(np.round(u).astype(np.int32), 0, w - 1)
    iv = np.clip(np.round(vv).astype(np.int32), 0, h - 1)
    disp = relief[iv, iu][:, None] * float(amp_m)
    mesh.vertices = v + nrm * disp


def _cbox(w: float, d: float, h: float, c: float | None = None) -> trimesh.Trimesh:
    m = mk.chamfer_box(w, d, h, c=c)
    c_mid = 0.5 * (m.bounds[0] + m.bounds[1])
    mk.place(m, -float(c_mid[0]), -float(c_mid[1]), -float(c_mid[2]))
    return m


def _parametric_knobby_mx_tire(
    r_major: float,
    r_sec: float,
    n_knobs: int = 26,
    knob_h: float = 0.0135,
    n_u: int = 152,
    n_v: int = 28,
) -> trimesh.Trimesh:
    t = mk.torus(r_major, r_sec * 0.88, major=n_u, minor=n_v)
    t_mid = 0.5 * (t.bounds[0] + t.bounds[1])
    t.apply_translation(-t_mid)
    mk.rot_y(t, 90.0)
    v = np.asarray(t.vertices, dtype=np.float64)
    nrm = np.asarray(t.vertex_normals, dtype=np.float64)

    uu = np.arctan2(v[:, 1], v[:, 2])
    rad_yz = np.hypot(v[:, 1], v[:, 2])
    sv = np.arctan2(v[:, 0], rad_yz - r_major)

    wave_c = np.clip(np.cos(n_knobs * uu) * 2.8, 0.0, 1.0)
    wave_s = np.clip(-np.cos(n_knobs * uu) * 2.8, 0.0, 1.0)

    c_band = np.exp(-((sv / 0.34) ** 4))
    m_band = np.exp(-(((np.abs(sv) - 0.58) / 0.19) ** 4))
    s_band = np.exp(-(((np.abs(sv) - 0.92) / 0.21) ** 4))

    disp = knob_h * (c_band * wave_c + 0.92 * m_band * wave_s + 0.78 * s_band * wave_c)
    t.vertices = v + nrm * disp[:, None]
    trimesh.repair.fix_normals(t)
    return t


def _build_3d_number_125(scale_h: float, thickness: float) -> trimesh.Trimesh:
    h = float(scale_h)
    w_d = h * 0.56
    st = h * 0.19
    parts: list[trimesh.Trimesh] = []

    def seg(x0: float, z0: float, x1: float, z1: float) -> None:
        dx, dz = x1 - x0, z1 - z0
        L = math.hypot(dx, dz) + st * 0.85
        bar = _cbox(L, thickness, st, c=st * 0.16)
        ang = math.degrees(math.atan2(dz, dx))
        mk.rot_y(bar, -ang)
        mk.place(bar, (x0 + x1) * 0.5, 0.0, (z0 + z1) * 0.5)
        parts.append(bar)

    x1c = -w_d * 1.18
    seg(x1c, -h * 0.44, x1c, +h * 0.44)
    seg(x1c - w_d * 0.24, +h * 0.26, x1c, +h * 0.44)

    x2l, x2r = -w_d * 0.42, +w_d * 0.18
    seg(x2l, +h * 0.44, x2r, +h * 0.44)
    seg(x2r, +h * 0.44, x2r, +h * 0.02)
    seg(x2l, +h * 0.02, x2r, +h * 0.02)
    seg(x2l, +h * 0.02, x2l, -h * 0.44)
    seg(x2l, -h * 0.44, x2r, -h * 0.44)

    x5l, x5r = +w_d * 0.60, +w_d * 1.20
    seg(x5l, +h * 0.44, x5r, +h * 0.44)
    seg(x5l, +h * 0.44, x5l, +h * 0.02)
    seg(x5l, +h * 0.02, x5r, +h * 0.02)
    seg(x5r, +h * 0.02, x5r, -h * 0.44)
    seg(x5l, -h * 0.44, x5r, -h * 0.44)

    return mk.union(parts)


def _build_mx_wheel(
    b: mk.Builder,
    tag: str,
    group_name: str,
    axle_y: float,
    axle_z: float,
    r_tire_outer: float,
    r_section: float,
    rim_width: float,
    n_knobs: int,
    n_spokes_side: int,
    m_tire: mk.Material,
    m_rim_blue: mk.Material,
    m_alu: mk.Material,
    m_steel: mk.Material,
    relief_rubber: np.ndarray | None,
) -> None:
    r_torus_major = r_tire_outer - r_section

    tire_mesh = _parametric_knobby_mx_tire(
        r_major=r_torus_major,
        r_sec=r_section,
        n_knobs=n_knobs,
        knob_h=r_section * 0.30,
        n_u=150,
        n_v=28,
    )
    _apply_gpu_micro_grain(tire_mesh, relief_rubber, amp_m=0.0006, scale=9.0)
    mk.place(tire_mesh, 0.0, axle_y, axle_z)
    b.add(tire_mesh, m_tire, name=f"mx_knobby_tire_{tag}", group=group_name)

    r_rim_in = r_torus_major - r_section * 0.96
    r_rim_out = r_torus_major - r_section * 0.56
    rim_main = mk.tube(r_rim_out, r_rim_in + 0.010, rim_width, sections=52)
    rim_drop = mk.tube(r_rim_in + 0.016, r_rim_in, rim_width * 0.58, sections=52)
    mk.place(rim_main, 0.0, 0.0, -rim_width * 0.5)
    mk.place(rim_drop, 0.0, 0.0, -rim_width * 0.29)

    hub_w = rim_width * 1.54
    r_hub = 0.050 if tag == "front" else 0.056
    hub_center = mk.cylinder(r_hub * 0.78, hub_w, sections=28)
    mk.place(hub_center, 0.0, 0.0, -hub_w * 0.5)
    flange_l = mk.cylinder(r_hub, hub_w * 0.24, sections=28)
    mk.place(flange_l, 0.0, 0.0, -hub_w * 0.46)
    flange_r = mk.cylinder(r_hub, hub_w * 0.24, sections=28)
    mk.place(flange_r, 0.0, 0.0, +hub_w * 0.22)
    hub_blue = mk.union([hub_center, flange_l, flange_r])

    rim_and_hub = mk.union([rim_main, rim_drop, hub_blue])
    mk.rot_y(rim_and_hub, 90.0)
    mk.place(rim_and_hub, 0.0, axle_y, axle_z)
    b.add(rim_and_hub, m_rim_blue, name=f"excel_blue_rim_and_hub_{tag}", group=group_name)

    axle_half = 0.114 if tag == "front" else 0.098
    axle_rod = mk.cylinder(0.016, axle_half * 2.0, sections=20)
    mk.rot_y(axle_rod, 90.0)
    mk.place(axle_rod, -axle_half, axle_y, axle_z)
    spacer_l = mk.cylinder(0.028, 0.036, sections=20)
    mk.rot_y(spacer_l, 90.0)
    mk.place(spacer_l, -axle_half, axle_y, axle_z)
    spacer_r = mk.cylinder(0.028, 0.036, sections=20)
    mk.rot_y(spacer_r, 90.0)
    mk.place(spacer_r, axle_half - 0.036, axle_y, axle_z)

    metal_wheel_parts: list[trimesh.Trimesh] = [axle_rod, spacer_l, spacer_r]
    hw = rim_width * 0.5
    for side_idx, sx in enumerate((-1.0, 1.0)):
        for k in range(n_spokes_side):
            a0 = (2.0 * math.pi * k) / n_spokes_side + (0.20 if side_idx else 0.0)
            cross = 0.36 if (k % 2 == 0) else -0.36
            a1 = a0 + cross
            p_hub = (
                sx * hub_w * 0.36,
                axle_y + (r_hub * 0.80) * math.sin(a0),
                axle_z + (r_hub * 0.80) * math.cos(a0),
            )
            p_rim = (
                sx * hw * 0.22,
                axle_y + (r_rim_in + 0.012) * math.sin(a1),
                axle_z + (r_rim_in + 0.012) * math.cos(a1),
            )
            sp = org.tapered_curve([p_hub, p_rim], [0.0042, 0.0038], sections=6, smooth_pts=3)
            p_nip0 = (
                sx * hw * 0.24,
                axle_y + (r_rim_in - 0.018) * math.sin(a1),
                axle_z + (r_rim_in - 0.018) * math.cos(a1),
            )
            nip = org.tapered_curve([p_nip0, p_rim], [0.0062, 0.0062], sections=6, smooth_pts=2)
            metal_wheel_parts.extend([sp, nip])
    b.add(mk.union(metal_wheel_parts), m_steel, name=f"stainless_spokes_nipples_and_axle_{tag}", group=group_name)


def _build_slotted_wave_disc(radius: float, thickness: float, x_pos: float, axle_y: float, axle_z: float, n_petals: int = 9) -> trimesh.Trimesh:
    n_pts = n_petals * 8
    pts_outer = []
    for i in range(n_pts):
        th = (2.0 * math.pi * i) / n_pts
        r = radius * (0.94 + 0.06 * math.cos(n_petals * th))
        pts_outer.append((r * math.cos(th), r * math.sin(th)))
    disc = mk.extrude(pts_outer, thickness)
    cutters = []
    for k in range(n_petals):
        th = (2.0 * math.pi * k) / n_petals
        slot = mk.cylinder(radius * 0.135, thickness * 3.0, sections=14)
        mk.place(slot, radius * 0.58 * math.cos(th), radius * 0.58 * math.sin(th), -thickness)
        cutters.append(slot)
    disc = mk.difference(disc, cutters)
    mk.rot_y(disc, 90.0)
    mk.place(disc, x_pos - thickness * 0.5, axle_y, axle_z)
    return disc


def build() -> mk.Builder:
    b = mk.Builder("yamaha_yz125")

    gpu_dir = Path(__file__).resolve().parent / "ai_gpu"
    relief_blue = _load_gpu_relief(gpu_dir / "tile_yamaha_racing_blue.png", "paint")
    relief_rubber = _load_gpu_relief(gpu_dir / "tile_mx_knobby_rubber.png", "rubber")
    relief_alu = _load_gpu_relief(gpu_dir / "tile_cnc_billet_alu.png", "alu")

    m_yz_blue = mk.mat.car_clearcoat("#0f4bef", roughness=0.16)
    m_yz_white = mk.mat.enamel("#f1f3f7", roughness=0.19)
    m_black_poly = mk.mat.abs_injected("#181b22", roughness=0.40)
    m_hose_blue = mk.mat.enamel("#1762f5", roughness=0.25)
    m_ngk_red = mk.mat.enamel("#dc2626", roughness=0.28)
    m_seat_blue = mk.mat.leather("#143eb8", roughness=0.56)
    m_seat_grip = mk.mat.rubber("#181b21", roughness=0.72)
    m_tire = mk.mat.knobby_rubber("#1f2227")
    m_rim_blue = mk.mat.anodized_alu("#1148db", roughness=0.20)
    m_alu_frame = mk.mat.brushed_stainless("#c8cfd8")
    m_cnc_dark = mk.mat.forged_iron("#2c313a")
    m_engine_alu = mk.mat.metal("#b2bac6", roughness=0.26, metallic=0.88)
    m_chrome = mk.mat.metal("#e6ebf2", roughness=0.08, metallic=0.96)
    m_pipe_2t = mk.mat.metal("#c5b8a2", roughness=0.17, metallic=0.92)
    m_pipe_weld = mk.mat.metal("#746584", roughness=0.25, metallic=0.90)
    m_gold_kyb = mk.mat.anodized_alu("#d8a736", roughness=0.21)
    m_stand_blk = mk.mat.paint("#222730", roughness=0.42)

    YF, ZF = -0.755, 0.348
    YR, ZR = +0.720, 0.326

    rake_deg = 26.5
    rk = math.radians(rake_deg)
    sr, cr = math.sin(rk), math.cos(rk)

    def _fork_pt(dist_up: float, x_off: float = 0.0, y_fwd: float = 0.0) -> tuple[float, float, float]:
        return (
            x_off,
            YF + dist_up * sr + y_fwd * cr,
            ZF + dist_up * cr - y_fwd * sr,
        )

    steer_piv = _fork_pt(0.635, 0.0, 0.034)
    b.def_joint("front_steering", pivot=steer_piv, axis=(0.0, sr, cr), kind="revolute")
    b.def_joint("front_wheel", pivot=(0.0, YF, ZF), axis=(1.0, 0.0, 0.0), kind="revolute", parent="front_steering")
    b.def_joint("rear_wheel", pivot=(0.0, YR, ZR), axis=(1.0, 0.0, 0.0), kind="revolute")
    b.def_joint("yz125_engine", pivot=(0.0, 0.025, 0.440), axis=(1.0, 0.0, 0.0), kind="fixed")

    # =========================================================================
    # 1. ROUES AVANT (21") ET ARRIÈRE (19") COMPLÈTES À 32 RAYONS CROISÉS + WAVE
    # =========================================================================
    _build_mx_wheel(
        b, "front", "front_wheel", YF, ZF,
        r_tire_outer=0.348, r_section=0.046, rim_width=0.068,
        n_knobs=28, n_spokes_side=16,
        m_tire=m_tire, m_rim_blue=m_rim_blue, m_alu=m_alu_frame,
        m_steel=m_chrome, relief_rubber=relief_rubber,
    )
    _build_mx_wheel(
        b, "rear", "rear_wheel", YR, ZR,
        r_tire_outer=0.326, r_section=0.058, rim_width=0.092,
        n_knobs=22, n_spokes_side=16,
        m_tire=m_tire, m_rim_blue=m_rim_blue, m_alu=m_alu_frame,
        m_steel=m_chrome, relief_rubber=relief_rubber,
    )

    f_disc = _build_slotted_wave_disc(0.138, 0.0065, -0.056, YF, ZF, n_petals=9)
    b.add(f_disc, m_alu_frame, name="front_wave_brake_disc", group="front_wheel")

    r_disc = _build_slotted_wave_disc(0.122, 0.0065, +0.062, YR, ZR, n_petals=8)
    b.add(r_disc, m_alu_frame, name="rear_wave_brake_disc", group="rear_wheel")

    n_teeth = 32
    sp_pts = []
    for i in range(n_teeth * 2):
        th = (2.0 * math.pi * i) / (n_teeth * 2)
        rr = 0.132 if (i % 2 == 0) else 0.120
        sp_pts.append((rr * math.cos(th), rr * math.sin(th)))
    sprocket = mk.extrude(sp_pts, 0.0085)
    sp_holes = []
    for k in range(6):
        th = (2.0 * math.pi * k) / 6.0
        hole = mk.cylinder(0.021, 0.030, sections=14)
        mk.place(hole, 0.078 * math.cos(th), 0.078 * math.sin(th), -0.010)
        sp_holes.append(hole)
    sprocket = mk.difference(sprocket, sp_holes)
    mk.rot_y(sprocket, 90.0)
    mk.place(sprocket, -0.066, YR, ZR)
    b.add(sprocket, m_rim_blue, name="rear_blue_racing_sprocket", group="rear_wheel")

    chain_up = org.tapered_curve(
        [(-0.063, +0.095, 0.434), (-0.063, +0.410, 0.448), (-0.063, YR, ZR + 0.124)],
        [0.0082, 0.0082, 0.0082],
        sections=10,
        smooth_pts=20,
    )
    chain_lo = org.tapered_curve(
        [(-0.063, +0.095, 0.376), (-0.063, +0.415, 0.285), (-0.063, YR, ZR - 0.124)],
        [0.0082, 0.0082, 0.0082],
        sections=10,
        smooth_pts=20,
    )
    front_sprocket = mk.cylinder(0.036, 0.012, sections=20)
    mk.rot_y(front_sprocket, 90.0)
    mk.place(front_sprocket, -0.069, +0.095, 0.405)
    b.add(mk.union([chain_up, chain_lo, front_sprocket]), m_gold_kyb, name="gold_520_mx_drive_chain")

    # =========================================================================
    # 2. DIRECTION AVANT ARTICULÉE (`front_steering`) : FOURCHE KYB SSS + POSTE DE PILOTAGE
    # =========================================================================
    fork_lower_parts: list[trimesh.Trimesh] = []
    fork_upper_parts: list[trimesh.Trimesh] = []
    fork_clamp_parts: list[trimesh.Trimesh] = []
    guard_parts: list[trimesh.Trimesh] = []
    fork_x = 0.104

    for sx in (-1.0, 1.0):
        lug = _cbox(0.044, 0.056, 0.072, c=0.007)
        mk.rot_x(lug, -rake_deg)
        mk.place(lug, sx * fork_x, YF, ZF)
        fork_lower_parts.append(lug)

        stanchion = org.tapered_curve(
            [_fork_pt(0.015, sx * fork_x), _fork_pt(0.395, sx * fork_x)],
            [0.022, 0.022],
            sections=22,
            smooth_pts=8,
        )
        fork_lower_parts.append(stanchion)

        outer_tube = org.tapered_curve(
            [_fork_pt(0.340, sx * fork_x), _fork_pt(0.790, sx * fork_x)],
            [0.0285, 0.0295],
            sections=24,
            smooth_pts=10,
        )
        fork_upper_parts.append(outer_tube)

        f_cap = mk.cylinder(0.026, 0.014, sections=20)
        mk.rot_x(f_cap, -rake_deg)
        cx_f, cy_f, cz_f = _fork_pt(0.792, sx * fork_x)
        mk.place(f_cap, cx_f, cy_f, cz_f)
        fork_clamp_parts.append(f_cap)

        guard = _cbox(0.054, 0.014, 0.300, c=0.005)
        mk.rot_x(guard, -rake_deg)
        gx, gy, gz = _fork_pt(0.185, sx * fork_x, y_fwd=-0.028)
        mk.place(guard, gx, gy, gz)
        guard_bridge = _cbox(0.046, 0.042, 0.042, c=0.004)
        mk.rot_x(guard_bridge, -rake_deg)
        bx, by, bz = _fork_pt(0.052, sx * fork_x, y_fwd=-0.012)
        mk.place(guard_bridge, bx, by, bz)
        guard_parts.extend([guard, guard_bridge])

    for d_cl in (0.555, 0.745):
        clamp = _cbox(fork_x * 2.0 + 0.066, 0.072, 0.028, c=0.006)
        mk.rot_x(clamp, -rake_deg)
        cx, cy, cz = _fork_pt(d_cl, 0.0, y_fwd=0.016)
        mk.place(clamp, cx, cy, cz)
        fork_clamp_parts.append(clamp)

    steer_stem = org.tapered_curve(
        [_fork_pt(0.530, 0.0, 0.034), _fork_pt(0.775, 0.0, 0.034)],
        [0.018, 0.018],
        sections=16,
        smooth_pts=6,
    )
    caliper_f = _cbox(0.052, 0.088, 0.076, c=0.008)
    mk.rot_x(caliper_f, -rake_deg)
    cal_x, cal_y, cal_z = _fork_pt(0.095, -0.076, y_fwd=+0.055)
    mk.place(caliper_f, cal_x, cal_y, cal_z)

    hb_x, hb_y, hb_z = _fork_pt(0.815, 0.0, y_fwd=0.018)
    risers = _cbox(0.118, 0.046, 0.052, c=0.006)
    mk.rot_x(risers, -rake_deg)
    mk.place(risers, hb_x, hb_y, hb_z - 0.02)

    hbar = org.tapered_curve(
        [
            (-0.400, hb_y + 0.055, hb_z + 0.068),
            (-0.215, hb_y + 0.024, hb_z + 0.042),
            (-0.075, hb_y, hb_z + 0.012),
            (+0.075, hb_y, hb_z + 0.012),
            (+0.215, hb_y + 0.024, hb_z + 0.042),
            (+0.400, hb_y + 0.055, hb_z + 0.068),
        ],
        [0.0115, 0.0125, 0.0145, 0.0145, 0.0125, 0.0115],
        sections=16,
        smooth_pts=36,
    )

    brake_hose = org.tapered_curve(
        [
            (cal_x - 0.012, cal_y + 0.010, cal_z + 0.030),
            (-fork_x - 0.018, YF + 0.145, ZF + 0.285),
            (-fork_x - 0.014, YF + 0.275, ZF + 0.560),
            (+0.185, hb_y + 0.015, hb_z + 0.038),
        ],
        [0.0046, 0.0044, 0.0044, 0.0046],
        sections=8,
        smooth_pts=28,
    )

    grips_parts: list[trimesh.Trimesh] = [hbar, caliper_f, steer_stem, risers, brake_hose]
    bar_pad = mk.cylinder(0.024, 0.175, sections=18)
    mk.rot_y(bar_pad, 90.0)
    mk.place(bar_pad, -0.088, hb_y + 0.006, hb_z + 0.024)
    grips_parts.append(bar_pad)

    lever_parts: list[trimesh.Trimesh] = []
    for sx in (-1.0, 1.0):
        grip = org.tapered_curve(
            [(sx * 0.285, hb_y + 0.034, hb_z + 0.050), (sx * 0.404, hb_y + 0.056, hb_z + 0.069)],
            [0.0165, 0.0165],
            sections=16,
            smooth_pts=8,
        )
        waffle_flange = mk.cylinder(0.027, 0.008, sections=18)
        mk.rot_y(waffle_flange, 90.0)
        mk.place(waffle_flange, sx * 0.282 - 0.004, hb_y + 0.034, hb_z + 0.050)
        perch = _cbox(0.028, 0.038, 0.038, c=0.004)
        mk.place(perch, sx * 0.258, hb_y + 0.028, hb_z + 0.048)
        grips_parts.extend([grip, waffle_flange, perch])

        lev = org.tapered_curve(
            [
                (sx * 0.258, hb_y + 0.010, hb_z + 0.044),
                (sx * 0.318, hb_y - 0.026, hb_z + 0.044),
                (sx * 0.382, hb_y - 0.018, hb_z + 0.052),
            ],
            [0.0065, 0.0052, 0.0075],
            sections=10,
            smooth_pts=14,
        )
        lever_parts.append(lev)

    b.add(mk.union(fork_lower_parts + lever_parts), m_chrome, name="kyb_fork_stanchions_and_levers", group="front_steering")
    b.add(mk.union(fork_upper_parts), m_gold_kyb, name="kyb_gold_outer_fork_tubes", group="front_steering")
    b.add(mk.union(fork_clamp_parts), m_rim_blue, name="cnc_blue_triple_clamps", group="front_steering")
    b.add(mk.union(grips_parts), m_seat_grip, name="pro_taper_cockpit_and_brake_line", group="front_steering")

    ff_pts = [
        (0.0, YF + 0.215, ZF + 0.455),
        (0.0, YF + 0.060, ZF + 0.478),
        (0.0, YF - 0.145, ZF + 0.468),
        (0.0, YF - 0.320, ZF + 0.415),
    ]
    f_fender = org.tapered_curve(ff_pts, [0.068, 0.064, 0.052, 0.032], sections=18, smooth_pts=28)
    v_ff = np.asarray(f_fender.vertices, dtype=np.float64)
    c_ff_z = float(v_ff[:, 2].mean())
    v_ff[:, 2] = c_ff_z + (v_ff[:, 2] - c_ff_z) * 0.24
    v_ff[:, 0] *= 1.30
    f_fender.vertices = v_ff
    ff_mount = _cbox(0.115, 0.085, 0.095)
    fx, fy, fz = _fork_pt(0.515, 0.0, y_fwd=-0.005)
    mk.place(ff_mount, fx, fy, fz)
    f_fender_full = mk.union([f_fender, ff_mount])
    _apply_gpu_micro_grain(f_fender_full, relief_blue, amp_m=0.00035, scale=5.0)
    b.add(f_fender_full, m_yz_blue, name="yamaha_front_fender", group="front_steering")

    front_plate = _cbox(0.228, 0.022, 0.242, c=0.018)
    mk.rot_x(front_plate, -rake_deg)
    px, py, pz = _fork_pt(0.680, 0.0, y_fwd=-0.034)
    mk.place(front_plate, px, py, pz)
    fp_mount = _cbox(0.120, 0.075, 0.060)
    mk.rot_x(fp_mount, -rake_deg)
    mx0, my0, mz0 = _fork_pt(0.660, 0.0, y_fwd=0.0)
    mk.place(fp_mount, mx0, my0, mz0)
    num_front = _build_3d_number_125(scale_h=0.082, thickness=0.018)
    mk.rot_x(num_front, -rake_deg)
    nx, ny, nz = _fork_pt(0.680, 0.0, y_fwd=-0.055)
    mk.place(num_front, nx, ny, nz)
    b.add(mk.union([*guard_parts, front_plate, fp_mount, num_front]), m_yz_white, name="front_plate_and_white_125", group="front_steering")

    front_black_bg = _cbox(0.186, 0.014, 0.136, c=0.010)
    mk.rot_x(front_black_bg, -rake_deg)
    bx, by, bz = _fork_pt(0.680, 0.0, y_fwd=-0.045)
    mk.place(front_black_bg, bx, by, bz)
    b.add(front_black_bg, m_black_poly, name="front_plate_black_125cc_bg", group="front_steering")

    # =========================================================================
    # 3. CHÂSSIS YAMAHA DELTABOX HYDROFORMÉ CAISSONNÉ + BRAS OSCILLANT CAISSONNÉ EFFILÉ
    # =========================================================================
    head_top = _fork_pt(0.765, 0.0, 0.034)
    head_bot = _fork_pt(0.540, 0.0, 0.034)
    frame_parts: list[trimesh.Trimesh] = []

    head_tube = org.tapered_curve([head_bot, head_top], [0.031, 0.029], sections=22, smooth_pts=8)
    neck_gusset = _box_beam(
        [
            (0.0, head_bot[1] + 0.020, head_bot[2] + 0.055),
            (0.0, -0.345, 0.735),
            (0.0, -0.255, 0.708),
        ],
        [(0.062, 0.092), (0.105, 0.086), (0.138, 0.072)],
        smooth_pts=14,
    )
    front_downtube = _box_beam(
        [
            (0.0, head_bot[1] + 0.012, head_bot[2] + 0.010),
            (0.0, -0.310, 0.625),
            (0.0, -0.215, 0.468),
        ],
        [(0.052, 0.068), (0.048, 0.062), (0.068, 0.056)],
        smooth_pts=16,
    )
    y_collector = _cbox(0.146, 0.075, 0.066, c=0.012)
    mk.rot_x(y_collector, -32.0)
    mk.place(y_collector, 0.0, -0.205, 0.455)

    skid_bottom = _cbox(0.196, 0.305, 0.014, c=0.004)
    mk.place(skid_bottom, 0.0, +0.020, 0.304)
    skid_front = _cbox(0.186, 0.014, 0.148, c=0.004)
    mk.rot_x(skid_front, +38.0)
    mk.place(skid_front, 0.0, -0.155, 0.365)
    frame_parts.extend([head_tube, neck_gusset, front_downtube, y_collector, skid_bottom, skid_front])

    frame_recess_cuts: list[trimesh.Trimesh] = []
    head_stays_blue: list[trimesh.Trimesh] = []
    axle_blocks_blue: list[trimesh.Trimesh] = []
    frame_bolts_chrome: list[trimesh.Trimesh] = []

    for sx in (-1.0, 1.0):
        spar = _box_beam(
            [
                (sx * 0.048, -0.335, 0.742),
                (sx * 0.088, -0.195, 0.728),
                (sx * 0.102, -0.015, 0.652),
                (sx * 0.104, +0.125, 0.525),
                (sx * 0.103, +0.180, 0.392),
            ],
            [
                (0.028, 0.058),
                (0.030, 0.066),
                (0.030, 0.068),
                (0.031, 0.082),
                (0.030, 0.108),
            ],
            smooth_pts=28,
        )
        piv_plate = _cbox(0.032, 0.116, 0.195, c=0.010)
        mk.rot_x(piv_plate, +12.0)
        mk.place(piv_plate, sx * 0.102, +0.175, 0.398)

        pocket_spar = _cbox(0.014, 0.068, 0.110, c=0.005)
        mk.rot_x(pocket_spar, +12.0)
        mk.place(pocket_spar, sx * 0.117, +0.172, 0.422)
        frame_recess_cuts.append(pocket_spar)

        cradle = _box_beam(
            [
                (sx * 0.048, -0.205, 0.455),
                (sx * 0.078, -0.125, 0.340),
                (sx * 0.082, +0.025, 0.312),
                (sx * 0.094, +0.145, 0.320),
                (sx * 0.102, +0.180, 0.388),
            ],
            [(0.026, 0.038), (0.024, 0.034), (0.024, 0.032), (0.026, 0.034), (0.028, 0.046)],
            smooth_pts=24,
        )

        sub_up = _box_beam(
            [(sx * 0.096, +0.155, 0.548), (sx * 0.084, +0.435, 0.706), (sx * 0.064, +0.705, 0.812)],
            [(0.022, 0.028), (0.020, 0.026), (0.018, 0.022)],
            smooth_pts=16,
        )
        sub_lo = _box_beam(
            [(sx * 0.098, +0.195, 0.435), (sx * 0.082, +0.460, 0.592), (sx * 0.064, +0.705, 0.812)],
            [(0.020, 0.024), (0.019, 0.022), (0.018, 0.022)],
            smooth_pts=16,
        )

        s_arm = _box_beam(
            [
                (sx * 0.096, +0.175, 0.395),
                (sx * 0.089, +0.365, 0.372),
                (sx * 0.081, +0.555, 0.348),
                (sx * 0.075, YR + 0.035, ZR),
            ],
            [
                (0.028, 0.072),
                (0.028, 0.078),
                (0.025, 0.062),
                (0.022, 0.046),
            ],
            smooth_pts=22,
        )
        pocket_sw = _box_beam(
            [
                (sx * 0.109, +0.275, 0.382),
                (sx * 0.101, +0.455, 0.360),
                (sx * 0.093, +0.605, 0.341),
            ],
            [(0.008, 0.032), (0.008, 0.028), (0.008, 0.022)],
            smooth_pts=12,
        )
        frame_recess_cuts.append(pocket_sw)
        frame_parts.extend([spar, piv_plate, cradle, sub_up, sub_lo, s_arm])

        h_stay = _cbox(0.014, 0.086, 0.092, c=0.005)
        mk.rot_x(h_stay, -22.0)
        mk.rot_z(h_stay, sx * 12.0)
        mk.place(h_stay, sx * 0.078, -0.055, 0.618)
        head_stays_blue.append(h_stay)

        ax_blk = _cbox(0.030, 0.058, 0.050, c=0.005)
        mk.place(ax_blk, sx * 0.076, YR + 0.006, ZR)
        axle_blocks_blue.append(ax_blk)

        piv_nut = mk.cylinder(0.016, 0.016, sections=12)
        mk.rot_y(piv_nut, 90.0)
        mk.place(piv_nut, sx * 0.112 - 0.008, +0.175, 0.395)
        sub_bolt = mk.cylinder(0.007, 0.016, sections=8)
        mk.rot_y(sub_bolt, 90.0)
        mk.place(sub_bolt, sx * 0.104 - 0.008, +0.160, 0.548)
        hs_bolt = mk.cylinder(0.0065, 0.016, sections=8)
        mk.rot_y(hs_bolt, 90.0)
        mk.place(hs_bolt, sx * 0.086 - 0.008, -0.068, 0.645)
        frame_bolts_chrome.extend([piv_nut, sub_bolt, hs_bolt])

    swing_bridge = _cbox(0.198, 0.095, 0.058, c=0.008)
    mk.place(swing_bridge, 0.0, +0.268, 0.382)
    prolink_bellcrank = _cbox(0.096, 0.088, 0.052, c=0.008)
    mk.place(prolink_bellcrank, 0.0, +0.235, 0.326)
    prolink_rod = _box_beam(
        [(0.0, +0.145, 0.322), (0.0, +0.245, 0.318)],
        [(0.068, 0.024), (0.068, 0.024)],
        smooth_pts=6,
    )
    shock_top_mount = _cbox(0.205, 0.072, 0.056, c=0.008)
    mk.place(shock_top_mount, 0.0, +0.115, 0.682)
    rear_caliper_bracket = _cbox(0.044, 0.085, 0.074, c=0.006)
    mk.place(rear_caliper_bracket, +0.068, YR - 0.055, ZR + 0.048)

    kickstarter = org.tapered_curve(
        [(+0.106, +0.108, 0.422), (+0.128, +0.098, 0.545), (+0.118, +0.062, 0.635), (+0.098, +0.058, 0.642)],
        [0.014, 0.0115, 0.011, 0.010],
        sections=14,
        smooth_pts=20,
    )
    brake_pedal = org.tapered_curve(
        [(+0.108, +0.145, 0.328), (+0.126, +0.015, 0.325), (+0.136, -0.052, 0.340)],
        [0.0105, 0.0095, 0.015],
        sections=10,
        smooth_pts=14,
    )
    shifter_arm = org.tapered_curve(
        [(-0.104, +0.022, 0.356), (-0.132, -0.058, 0.342), (-0.124, -0.102, 0.350)],
        [0.0105, 0.009, 0.0095],
        sections=10,
        smooth_pts=14,
    )
    frame_bolts_chrome.extend([kickstarter, brake_pedal, shifter_arm])

    frame_parts.extend([swing_bridge, prolink_bellcrank, prolink_rod, shock_top_mount, rear_caliper_bracket])
    frame_merged = mk.difference(mk.union(frame_parts), frame_recess_cuts)
    _apply_gpu_micro_grain(frame_merged, relief_alu, amp_m=0.0003, scale=8.0)
    b.add(frame_merged, m_alu_frame, name="yamaha_deltabox_hydroformed_frame_and_swingarm")

    shifter_tip = mk.cylinder(0.0115, 0.036, sections=14)
    mk.rot_y(shifter_tip, -90.0)
    mk.place(shifter_tip, -0.116, -0.102, 0.350)
    b.add(mk.union([shifter_tip, *head_stays_blue, *axle_blocks_blue]), m_rim_blue, name="cnc_blue_head_stays_axle_blocks_shifter")
    b.add(mk.union(frame_bolts_chrome), m_chrome, name="frame_pivot_bolts_kickstarter_controls")

    pegs_and_guides: list[trimesh.Trimesh] = []
    for sx in (-1.0, 1.0):
        peg = _cbox(0.112, 0.054, 0.022, c=0.003)
        mk.place(peg, sx * 0.142, +0.152, 0.318)
        pegs_and_guides.append(peg)
    chain_slider = _cbox(0.036, 0.165, 0.024, c=0.005)
    mk.rot_x(chain_slider, -4.0)
    mk.place(chain_slider, -0.068, +0.265, 0.432)
    chain_guide_lower = _cbox(0.038, 0.115, 0.078, c=0.006)
    mk.place(chain_guide_lower, -0.066, YR - 0.105, ZR - 0.108)
    pegs_and_guides.extend([chain_slider, chain_guide_lower])
    b.add(mk.union(pegs_and_guides), m_cnc_dark, name="footpegs_chain_slider_and_lower_chain_guide")

    shock_p0 = np.array([0.0, +0.115, 0.680])
    shock_p1 = np.array([0.0, +0.235, 0.335])
    shock_body = org.tapered_curve([tuple(shock_p0), (0.0, +0.165, 0.540)], [0.026, 0.024], sections=18, smooth_pts=6)
    shock_rod = org.tapered_curve([(0.0, +0.162, 0.548), tuple(shock_p1)], [0.014, 0.014], sections=16, smooth_pts=6)
    b.add(mk.union([shock_body, shock_rod]), m_chrome, name="kyb_shock_damper_shaft")

    spring = mk.helix_spring(r_coil=0.040, r_wire=0.0082, pitch=0.028, turns=6.8, sections=12, pts_per_turn=18)
    ang_sh = math.degrees(math.atan2(shock_p1[1] - shock_p0[1], shock_p0[2] - shock_p1[2]))
    mk.rot_x(spring, -ang_sh)
    mk.place(spring, 0.0, +0.186, 0.478)
    b.add(spring, m_rim_blue, name="kyb_coil_spring_blue")

    piggyback = mk.cylinder(0.027, 0.118, sections=22)
    mk.rot_x(piggyback, -66.0)
    mk.place(piggyback, +0.044, +0.155, 0.652)
    piggy_bridge = _cbox(0.072, 0.048, 0.048, c=0.006)
    mk.place(piggy_bridge, +0.020, +0.128, 0.668)
    b.add(mk.union([piggyback, piggy_bridge]), m_gold_kyb, name="kyb_piggyback_reservoir")

    # =========================================================================
    # 4. MOTEUR 125 cc 2-TEMPS LIQUIDE YPVS PLEIN VOLUME — ZÉRO VIDE DANS LE CADRE (`yz125_engine`)
    # =========================================================================
    eng_parts: list[trimesh.Trimesh] = []
    crank_front = org.superellipsoid(0.080, 0.115, 0.088, e1=0.52, e2=0.60, center=(0.0, -0.005, 0.415))
    gearbox_rear = org.superellipsoid(0.084, 0.125, 0.086, e1=0.48, e2=0.58, center=(0.0, +0.105, 0.408))
    pivot_boss_rear = mk.cylinder(0.036, 0.214, sections=22)
    mk.rot_y(pivot_boss_rear, 90.0)
    mk.place(pivot_boss_rear, -0.107, +0.175, 0.395)
    case_seam = _cbox(0.014, 0.335, 0.185, c=0.004)
    mk.place(case_seam, 0.0, +0.052, 0.408)
    reed_case = _cbox(0.098, 0.084, 0.084, c=0.010)
    mk.rot_x(reed_case, -16.0)
    mk.place(reed_case, 0.0, +0.048, 0.495)
    sprocket_guard = _cbox(0.032, 0.076, 0.092, c=0.008)
    mk.place(sprocket_guard, -0.084, +0.098, 0.410)
    eng_parts.extend([crank_front, gearbox_rear, pivot_boss_rear, case_seam, reed_case, sprocket_guard])

    cyl_barrel = mk.cylinder(0.064, 0.156, sections=30)
    mk.rot_x(cyl_barrel, -16.0)
    mk.place(cyl_barrel, 0.0, -0.032, 0.542)
    cyl_base_flange = _cbox(0.146, 0.142, 0.018, c=0.014)
    mk.rot_x(cyl_base_flange, -16.0)
    mk.place(cyl_base_flange, 0.0, -0.016, 0.478)
    ex_flange = _cbox(0.086, 0.062, 0.062, c=0.010)
    mk.rot_x(ex_flange, -16.0)
    mk.place(ex_flange, 0.010, -0.084, 0.538)
    eng_parts.extend([cyl_barrel, cyl_base_flange, ex_flange])

    for sx in (-1.0, 1.0):
        tr_bulge = org.ellipsoid(0.038, 0.056, 0.066, center=(0.0, 0.0, 0.0))
        mk.rot_x(tr_bulge, -16.0)
        mk.place(tr_bulge, sx * 0.056, -0.032, 0.552)
        eng_parts.append(tr_bulge)

    for rib_i in range(6):
        t_r = rib_i / 5.0
        w_span = 0.152 + 0.014 * math.sin(math.pi * t_r)
        w_rib = _cbox(w_span, 0.138, 0.0072, c=0.0025)
        mk.rot_x(w_rib, -16.0)
        mk.place(w_rib, 0.0, -0.018 - 0.034 * t_r, 0.494 + 0.112 * t_r)
        eng_parts.append(w_rib)

    ypvs_housing = _cbox(0.052, 0.068, 0.062, c=0.009)
    mk.rot_x(ypvs_housing, -16.0)
    mk.place(ypvs_housing, +0.066, -0.042, 0.558)
    wp_volute = mk.cylinder(0.039, 0.046, sections=24)
    mk.rot_y(wp_volute, 90.0)
    mk.place(wp_volute, +0.072, -0.048, 0.432)
    wp_spigot = org.tapered_curve([(+0.094, -0.055, 0.456), (+0.090, -0.098, 0.488)], [0.014, 0.012], sections=12, smooth_pts=8)
    eng_parts.extend([ypvs_housing, wp_volute, wp_spigot])

    carb_body = _cbox(0.086, 0.088, 0.092, c=0.010)
    mk.place(carb_body, -0.004, +0.105, 0.535)
    float_bowl = _cbox(0.078, 0.076, 0.058, c=0.009)
    mk.place(float_bowl, -0.004, +0.106, 0.476)
    bellmouth = mk.cylinder(0.044, 0.042, sections=22)
    mk.rot_x(bellmouth, -82.0)
    mk.place(bellmouth, -0.004, +0.148, 0.542)
    eng_parts.extend([carb_body, float_bowl, bellmouth])
    b.add(mk.union(eng_parts), m_engine_alu, name="yamaha_yz125_liquid_ypvs_full_block", group="yz125_engine")

    vhm_base = mk.cylinder(0.074, 0.028, sections=30)
    mk.rot_x(vhm_base, -16.0)
    mk.place(vhm_base, 0.0, -0.054, 0.622)
    vhm_crown = mk.cylinder(0.054, 0.022, sections=28)
    mk.rot_x(vhm_crown, -16.0)
    mk.place(vhm_crown, 0.0, -0.060, 0.642)
    vhm_spigot = org.tapered_curve([(0.0, -0.062, 0.648), (0.0, -0.106, 0.678)], [0.015, 0.013], sections=12, smooth_pts=8)
    ypvs_gold_cap = mk.cylinder(0.021, 0.014, sections=18)
    mk.rot_y(ypvs_gold_cap, 90.0)
    mk.place(ypvs_gold_cap, +0.088, -0.042, 0.558)
    drain_plug = mk.cylinder(0.010, 0.020, sections=10)
    mk.place(drain_plug, -0.004, +0.106, 0.446)
    gytr_badge = mk.cylinder(0.038, 0.015, sections=24)
    mk.rot_y(gytr_badge, 90.0)
    mk.place(gytr_badge, +0.112, +0.058, 0.412)
    ign_center_plug = mk.cylinder(0.024, 0.015, sections=20)
    mk.rot_y(ign_center_plug, 90.0)
    mk.place(ign_center_plug, -0.125, +0.012, 0.412)
    ign_tdc_plug = mk.cylinder(0.012, 0.016, sections=14)
    mk.rot_y(ign_tdc_plug, 90.0)
    mk.place(ign_tdc_plug, -0.124, -0.012, 0.452)
    carb_screw_air = mk.cylinder(0.0075, 0.020, sections=10)
    mk.rot_y(carb_screw_air, 90.0)
    mk.place(carb_screw_air, -0.054, +0.118, 0.545)
    carb_screw_idle = mk.cylinder(0.0075, 0.020, sections=10)
    mk.rot_y(carb_screw_idle, 90.0)
    mk.place(carb_screw_idle, -0.054, +0.092, 0.525)
    b.add(
        mk.union([
            vhm_base, vhm_crown, vhm_spigot, ypvs_gold_cap, drain_plug,
            gytr_badge, ign_center_plug, ign_tdc_plug, carb_screw_air, carb_screw_idle,
        ]),
        m_gold_kyb,
        name="vhm_gold_cnc_head_and_billet_badges",
        group="yz125_engine",
    )

    bolts_and_springs: list[trimesh.Trimesh] = []
    for k_b in range(6):
        ang_b = (2.0 * math.pi * k_b) / 6.0
        acorn = mk.cylinder(0.0068, 0.026, sections=8)
        mk.rot_x(acorn, -16.0)
        mk.place(
            acorn,
            0.058 * math.cos(ang_b),
            -0.056 + 0.055 * math.sin(ang_b),
            0.634 - 0.015 * math.sin(ang_b),
        )
        bolts_and_springs.append(acorn)

    for k_c in range(8):
        ang_c = (2.0 * math.pi * k_c) / 8.0
        m6 = mk.cylinder(0.0058, 0.016, sections=6)
        mk.rot_y(m6, 90.0)
        mk.place(m6, +0.109, +0.058 + 0.058 * math.sin(ang_c), 0.412 + 0.058 * math.cos(ang_c))
        bolts_and_springs.append(m6)

    for k_w in range(4):
        ang_w = (2.0 * math.pi * k_w) / 4.0 + 0.4
        m6w = mk.cylinder(0.0050, 0.016, sections=6)
        mk.rot_y(m6w, 90.0)
        mk.place(m6w, +0.107, -0.048 + 0.026 * math.sin(ang_w), 0.432 + 0.026 * math.cos(ang_w))
        bolts_and_springs.append(m6w)

    for k_i in range(6):
        ang_i = (2.0 * math.pi * k_i) / 6.0
        m6i = mk.cylinder(0.0056, 0.016, sections=6)
        mk.rot_y(m6i, 90.0)
        mk.place(m6i, -0.123, +0.012 + 0.050 * math.sin(ang_i), 0.412 + 0.050 * math.cos(ang_i))
        bolts_and_springs.append(m6i)

    for y_cl, z_cl, r_cl in ((+0.068, 0.515, 0.046), (+0.158, 0.550, 0.048)):
        clamp_ring = mk.torus(r_cl, 0.0040, major=24, minor=8)
        mk.rot_x(clamp_ring, 82.0)
        mk.place(clamp_ring, -0.004, y_cl, z_cl)
        bolts_and_springs.append(clamp_ring)

    for sx_sp in (-1.0, 1.0):
        ex_sp = mk.helix_spring(r_coil=0.0072, r_wire=0.0019, pitch=0.0068, turns=4.5, sections=8, pts_per_turn=12)
        mk.rot_x(ex_sp, 72.0)
        mk.place(ex_sp, 0.012 + sx_sp * 0.028, -0.106, 0.548)
        sp_core = org.tapered_curve(
            [(0.012 + sx_sp * 0.028, -0.078, 0.554), (0.012 + sx_sp * 0.028, -0.132, 0.568)],
            [0.0038, 0.0038],
            sections=8,
            smooth_pts=6,
        )
        bolts_and_springs.extend([ex_sp, sp_core])

    b.add(mk.union(bolts_and_springs), m_chrome, name="chrome_head_nuts_m6_bolts_exhaust_springs", group="yz125_engine")

    covers: list[trimesh.Trimesh] = []
    clutch_cov = mk.cylinder(0.078, 0.048, sections=32)
    mk.rot_y(clutch_cov, 90.0)
    mk.place(clutch_cov, +0.070, +0.058, 0.412)

    ign_cov = mk.cylinder(0.074, 0.048, sections=30)
    mk.rot_y(ign_cov, 90.0)
    mk.place(ign_cov, -0.118, +0.012, 0.412)

    vforce_block = _cbox(0.094, 0.044, 0.078, c=0.006)
    mk.place(vforce_block, -0.002, +0.068, 0.518)
    air_boot = org.tapered_curve(
        [(-0.004, +0.145, 0.548), (-0.012, +0.215, 0.578), (0.0, +0.295, 0.618)],
        [0.046, 0.055, 0.066],
        sections=22,
        smooth_pts=16,
    )
    choke_knob = mk.cylinder(0.0105, 0.030, sections=12)
    mk.rot_y(choke_knob, 90.0)
    mk.place(choke_knob, -0.056, +0.105, 0.578)
    ign_coil = _cbox(0.052, 0.068, 0.048, c=0.008)
    mk.place(ign_coil, 0.0, -0.145, 0.708)
    throttle_cable = org.tapered_curve(
        [(-0.004, +0.105, 0.598), (-0.018, +0.035, 0.668), (+0.035, -0.145, 0.768), (+0.110, -0.328, 0.885)],
        [0.0044, 0.0040, 0.0040, 0.0040],
        sections=8,
        smooth_pts=24,
    )
    covers.extend([clutch_cov, ign_cov, vforce_block, air_boot, choke_knob, ign_coil, throttle_cable])
    b.add(mk.union(covers), m_cnc_dark, name="gytr_billet_clutch_vforce_and_airboot", group="yz125_engine")

    carb_cap_blue = mk.cylinder(0.028, 0.024, sections=20)
    mk.place(carb_cap_blue, -0.004, +0.105, 0.580)
    oil_cap_blue = mk.cylinder(0.014, 0.024, sections=14)
    mk.rot_x(oil_cap_blue, -30.0)
    mk.place(oil_cap_blue, +0.098, +0.098, 0.478)
    sight_ring = mk.cylinder(0.012, 0.016, sections=14)
    mk.rot_y(sight_ring, 90.0)
    mk.place(sight_ring, +0.109, +0.010, 0.382)
    b.add(mk.union([carb_cap_blue, oil_cap_blue, sight_ring]), m_rim_blue, name="keihin_blue_slide_cap_and_oil_cap", group="yz125_engine")

    spark_cap = mk.cylinder(0.017, 0.048, sections=16)
    mk.rot_x(spark_cap, -16.0)
    mk.place(spark_cap, 0.0, -0.068, 0.652)
    ht_wire = org.tapered_curve([(0.0, -0.075, 0.682), (0.012, -0.112, 0.698), (0.0, -0.145, 0.708)], [0.0058, 0.0058, 0.0058], sections=8, smooth_pts=14)
    vent_1 = org.tapered_curve([(-0.032, +0.108, 0.468), (-0.058, +0.145, 0.402), (-0.062, +0.172, 0.348)], [0.0044, 0.0044, 0.0044], sections=8, smooth_pts=12)
    vent_2 = org.tapered_curve([(+0.026, +0.108, 0.468), (+0.055, +0.148, 0.402), (+0.062, +0.172, 0.348)], [0.0044, 0.0044, 0.0044], sections=8, smooth_pts=12)
    b.add(mk.union([spark_cap, ht_wire, vent_1, vent_2]), m_ngk_red, name="ngk_spark_boot_and_keihin_vent_lines", group="yz125_engine")

    rads: list[trimesh.Trimesh] = []
    rad_louvers: list[trimesh.Trimesh] = []
    hoses: list[trimesh.Trimesh] = []
    for sx in (-1.0, 1.0):
        rad = _cbox(0.052, 0.125, 0.255, c=0.008)
        mk.rot_x(rad, -16.0)
        mk.place(rad, sx * 0.088, -0.185, 0.635)
        rads.append(rad)

        for lv_i in range(6):
            lv = _cbox(0.056, 0.010, 0.024, c=0.002)
            mk.rot_x(lv, +24.0)
            mk.place(lv, sx * 0.088, -0.232 + 0.010 * lv_i, 0.545 + 0.034 * lv_i)
            rad_louvers.append(lv)

        hose_up = org.tapered_curve(
            [(0.0, -0.098, 0.672), (sx * 0.056, -0.138, 0.688), (sx * 0.086, -0.178, 0.725)],
            [0.0125, 0.0125, 0.0125],
            sections=12,
            smooth_pts=16,
        )
        hoses.append(hose_up)

    rad_cap = mk.cylinder(0.018, 0.022, sections=16)
    mk.rot_x(rad_cap, -16.0)
    mk.place(rad_cap, +0.092, -0.222, 0.762)
    rads.append(rad_cap)

    hose_lo = org.tapered_curve(
        [(+0.088, -0.150, 0.520), (+0.095, -0.118, 0.496), (+0.090, -0.088, 0.478)],
        [0.0125, 0.0125, 0.0125],
        sections=12,
        smooth_pts=16,
    )
    hose_cross = org.tapered_curve(
        [(-0.088, -0.150, 0.520), (0.0, -0.155, 0.502), (+0.088, -0.150, 0.520)],
        [0.011, 0.011, 0.011],
        sections=12,
        smooth_pts=14,
    )
    hoses.extend([hose_lo, hose_cross])
    b.add(mk.union(rads), m_alu_frame, name="twin_oversized_aluminum_radiators")
    b.add(mk.union(hoses), m_hose_blue, name="factory_blue_silicone_hoses", group="yz125_engine")

    pipe_pts = [
        (0.012, -0.085, 0.548),
        (0.048, -0.195, 0.520),
        (0.112, -0.245, 0.468),
        (0.146, -0.155, 0.448),
        (0.152, -0.015, 0.482),
        (0.136, +0.125, 0.542),
        (0.106, +0.255, 0.612),
        (0.098, +0.405, 0.682),
    ]
    pipe_radii = [0.025, 0.032, 0.044, 0.062, 0.065, 0.048, 0.019, 0.017]
    expansion_pipe = org.tapered_curve(pipe_pts, pipe_radii, sections=28, smooth_pts=60)
    pipe_mount = _cbox(0.062, 0.038, 0.038, c=0.005)
    mk.place(pipe_mount, +0.112, -0.015, 0.482)
    b.add(mk.union([expansion_pipe, pipe_mount]), m_pipe_2t, name="two_stroke_works_expansion_chamber")

    weld_rings: list[trimesh.Trimesh] = []
    for idx_w in (2, 3, 4, 5):
        p_prev = np.asarray(pipe_pts[idx_w - 1], dtype=np.float64)
        p_next = np.asarray(pipe_pts[idx_w + 1], dtype=np.float64)
        tangent = p_next - p_prev
        tangent /= np.linalg.norm(tangent)
        ring = mk.torus(pipe_radii[idx_w] + 0.0018, 0.0032, major=28, minor=10)
        z_ax = np.array([0.0, 0.0, 1.0])
        v_cr = np.cross(z_ax, tangent)
        s_val = np.linalg.norm(v_cr)
        c_val = float(np.dot(z_ax, tangent))
        if s_val > 1e-6:
            vx = np.array([[0, -v_cr[2], v_cr[1]], [v_cr[2], 0, -v_cr[0]], [-v_cr[1], v_cr[0], 0]])
            R3 = np.eye(3) + vx + (vx @ vx) * ((1.0 - c_val) / (s_val ** 2))
            T4 = np.eye(4)
            T4[:3, :3] = R3
            ring.apply_transform(T4)
        mk.place(ring, *pipe_pts[idx_w])
        weld_rings.append(ring)
    b.add(mk.union(weld_rings), m_pipe_weld, name="works_pipe_heat_weld_seams")

    silencer_body = org.tapered_curve(
        [(0.098, +0.395, 0.678), (0.096, +0.715, 0.806)],
        [0.034, 0.033],
        sections=24,
        smooth_pts=12,
    )
    sil_mount = _cbox(0.058, 0.038, 0.038, c=0.005)
    mk.place(sil_mount, +0.078, +0.560, 0.745)
    b.add(mk.union([silencer_body, sil_mount]), m_alu_frame, name="pro_2stroke_aluminum_silencer")

    silencer_tip = org.tapered_curve(
        [(0.096, +0.708, 0.802), (0.095, +0.768, 0.824)],
        [0.032, 0.019],
        sections=20,
        smooth_pts=8,
    )
    b.add(silencer_tip, m_black_poly, name="carbon_silencer_endcap")

    # =========================================================================
    # 5. HABILLAGE PLASTIQUE YAMAHA YZ125 + BOÎTE À AIR PROFONDE + PLAQUES #125 NETTES
    # =========================================================================
    body_sc = org.Sculpt(bounds=((-0.20, -0.36, 0.56), (0.20, 1.02, 1.00)), res=78)
    body_sc.ellipsoid((0.0, -0.135, 0.790), (0.092, 0.175, 0.096), k=0.018)
    body_sc.sweep(
        [
            (0.0, +0.320, 0.782),
            (0.0, +0.560, 0.832),
            (0.0, +0.785, 0.882),
            (0.0, +0.968, 0.904),
        ],
        [0.080, 0.070, 0.055, 0.032],
        k=0.015,
    )
    body_sc.sweep(
        [(0.0, +0.520, 0.760), (0.0, +0.785, 0.822), (0.0, +0.980, 0.854)],
        [0.065, 0.055, 0.045],
        mode="sub",
        k=0.011,
    )
    tank_tail = body_sc.to_mesh(smooth_iter=4, target_tris=5200)

    shroud_poly_yz = [
        (-0.035, 0.848),
        (-0.215, 0.838),
        (-0.470, 0.770),
        (-0.310, 0.652),
        (-0.278, 0.505),
        (-0.140, 0.552),
        (-0.035, 0.695),
    ]
    shroud_wings: list[trimesh.Trimesh] = [tank_tail]
    graphic_stripes_white: list[trimesh.Trimesh] = []
    black_number_bgs: list[trimesh.Trimesh] = []

    for sx in (-1.0, 1.0):
        wing = mk.extrude(shroud_poly_yz, 0.022)
        vent_cut = _cbox(0.095, 0.028, 0.060, c=0.006)
        mk.rot_z(vent_cut, -18.0)
        mk.place(vent_cut, -0.245, 0.695, +0.010)
        wing = mk.difference(wing, [vent_cut])
        verts = np.asarray(wing.vertices, dtype=np.float64)
        new_v = np.column_stack([
            sx * (verts[:, 2] + 0.098 + 0.055 * np.clip((-verts[:, 0] - 0.05) / 0.38, 0.0, 1.0)),
            verts[:, 0],
            verts[:, 1],
        ])
        if sx < 0:
            wing.faces = wing.faces[:, ::-1]
        wing.vertices = new_v
        shroud_wings.append(wing)

        w_bridge = _cbox(0.068, 0.150, 0.130)
        mk.place(w_bridge, sx * 0.088, -0.175, 0.735)
        shroud_wings.append(w_bridge)

        stripe_poly = [
            (-0.055, 0.814),
            (-0.428, 0.768),
            (-0.352, 0.716),
            (-0.055, 0.762),
        ]
        st_mesh = mk.extrude(stripe_poly, 0.012)
        sv = np.asarray(st_mesh.vertices, dtype=np.float64)
        st_v = np.column_stack([
            sx * (sv[:, 2] + 0.116 + 0.055 * np.clip((-sv[:, 0] - 0.05) / 0.38, 0.0, 1.0)),
            sv[:, 0],
            sv[:, 1],
        ])
        if sx < 0:
            st_mesh.faces = st_mesh.faces[:, ::-1]
        st_mesh.vertices = st_v
        graphic_stripes_white.append(st_mesh)

    blue_body = mk.union(shroud_wings)
    _apply_gpu_micro_grain(blue_body, relief_blue, amp_m=0.00035, scale=5.0)
    b.add(blue_body, m_yz_blue, name="yamaha_tank_shrouds_rear_fender")

    gas_cap = mk.cylinder(0.036, 0.028, sections=22)
    mk.place(gas_cap, 0.0, -0.165, 0.865)
    vent_hose = org.tapered_curve([(0.0, -0.165, 0.892), (0.0, -0.245, 0.905), (0.0, -0.320, 0.845)], [0.0045, 0.0045, 0.0045], sections=8, smooth_pts=12)

    airbox_upper = _cbox(0.162, 0.255, 0.215, c=0.018)
    mk.place(airbox_upper, 0.0, +0.345, 0.682)
    airbox_lower = _cbox(0.146, 0.195, 0.165, c=0.018)
    mk.rot_x(airbox_lower, +22.0)
    mk.place(airbox_lower, 0.0, +0.295, 0.565)
    mud_flap = _cbox(0.148, 0.014, 0.165, c=0.006)
    mk.rot_x(mud_flap, -14.0)
    mk.place(mud_flap, 0.0, +0.398, 0.455)

    seat_sc = org.Sculpt(bounds=((-0.14, -0.12, 0.72), (0.14, 0.66, 0.94)), res=68)
    seat_sc.sweep(
        [
            (0.0, -0.055, 0.858),
            (0.0, +0.095, 0.830),
            (0.0, +0.265, 0.824),
            (0.0, +0.465, 0.847),
            (0.0, +0.605, 0.864),
        ],
        [0.054, 0.074, 0.076, 0.068, 0.045],
        k=0.014,
    )
    seat_mesh = seat_sc.to_mesh(smooth_iter=4, target_tris=2800)
    b.add(seat_mesh, m_seat_blue, name="yamaha_gripper_racing_seat")

    seat_ribs: list[trimesh.Trimesh] = []
    for ri in range(5):
        ry_rib = +0.160 + 0.076 * ri
        rz_rib = 0.870 + 0.005 * ri
        rib = org.curved_visor(width=0.118, length=0.019, thickness=0.024, arch=0.014, droop=0.0, sections=14)
        mk.place(rib, 0.0, ry_rib, rz_rib)
        seat_ribs.append(rib)
    b.add(mk.union(seat_ribs), m_seat_grip, name="seat_gripper_ribs")

    white_side_parts: list[trimesh.Trimesh] = [*graphic_stripes_white]
    for sx in (-1.0, 1.0):
        side_poly = [
            (+0.265, 0.778),
            (+0.465, 0.798),
            (+0.728, 0.845),
            (+0.635, 0.708),
            (+0.432, 0.642),
            (+0.275, 0.692),
        ]
        sp_mesh = mk.extrude(side_poly, 0.018)
        spv = np.asarray(sp_mesh.vertices, dtype=np.float64)
        sp_mesh.vertices = np.column_stack([sx * (spv[:, 2] + 0.098), spv[:, 0], spv[:, 1]])
        if sx < 0:
            sp_mesh.faces = sp_mesh.faces[:, ::-1]
        white_side_parts.append(sp_mesh)

        sp_bridge = _cbox(0.058, 0.165, 0.085)
        mk.place(sp_bridge, sx * 0.080, +0.450, 0.735)
        white_side_parts.append(sp_bridge)

        bg_side = _cbox(0.012, 0.220, 0.106, c=0.008)
        mk.rot_x(bg_side, 6.0)
        mk.place(bg_side, sx * 0.116, +0.472, 0.742)
        black_number_bgs.append(bg_side)

        num_side = _build_3d_number_125(scale_h=0.072, thickness=0.018)
        mk.rot_z(num_side, +90.0 if sx > 0 else -90.0)
        mk.place(num_side, sx * 0.125, +0.472, 0.742)
        white_side_parts.append(num_side)

    b.add(mk.union(white_side_parts), m_yz_white, name="factory_white_side_plates_and_125")
    b.add(
        mk.union([gas_cap, vent_hose, airbox_upper, airbox_lower, mud_flap, *rad_louvers, *black_number_bgs]),
        m_black_poly,
        name="black_airbox_louvers_and_125cc_backgrounds",
    )

    # =========================================================================
    # 6. LÈVE-MOTO PADDOCK SOUS LE SABOT MOTEUR (MONOBLOC `bodies == 1` GARANTI)
    # =========================================================================
    stand_parts: list[trimesh.Trimesh] = []
    top_pad = _cbox(0.240, 0.285, 0.032, c=0.006)
    mk.place(top_pad, 0.0, +0.035, 0.296)
    base_ring = _cbox(0.290, 0.335, 0.022, c=0.006)
    mk.place(base_ring, 0.0, +0.035, 0.011)
    stand_parts.extend([top_pad, base_ring])
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            leg = org.tapered_curve(
                [(sx * 0.128, +0.035 + sy * 0.145, 0.010), (sx * 0.102, +0.035 + sy * 0.120, 0.296)],
                [0.0135, 0.0125],
                sections=12,
                smooth_pts=6,
            )
            stand_parts.append(leg)
    b.add(mk.union(stand_parts), m_stand_blk, name="mx_paddock_race_stand")

    full_solid = b.union_solid()
    z_min = float(full_solid.bounds[0, 2])
    if abs(z_min) > 1e-6:
        for mesh_p, _, _ in b._parts:
            mesh_p.apply_translation([0.0, 0.0, -z_min])
        for j_meta in b._joints.values():
            j_meta["pivot"][2] = float(j_meta["pivot"][2]) - z_min

    b.def_socket("SOCKET_rider_seat", (0.0, +0.200, 0.855 - z_min))
    b.def_socket("SOCKET_exhaust_tip", (+0.095, +0.768, 0.824 - z_min))
    return b


if __name__ == "__main__":
    import game_ready as _gr
    import preview as _pv
    import renderer as _rn

    t0 = time.perf_counter()
    out_dir = Path("exports/yamaha_yz125")
    out_dir.mkdir(parents=True, exist_ok=True)

    builder = build()
    stl_out = out_dir / "yamaha_yz125.stl"
    mk.export_stl(builder.union_solid(), stl_out)

    res = _gr.export_game_package(
        builder,
        out_dir=out_dir,
        name="yamaha_yz125",
        engine="roblox_unreal",
        lod0_tris=9600,
        tex_size=1024,
    )
    glb_path = out_dir / "yamaha_yz125_game.glb"
    sc = trimesh.load(glb_path, force="scene")

    views_full = [
        (_rn.render_view(sc, azimuth_deg=56.0, elevation_deg=15.0, size=680, fov=35.0), "3/4 Avant Droit — Roue 32 Rayons + Pot Works"),
        (_rn.render_view(sc, azimuth_deg=-56.0, elevation_deg=15.0, size=680, fov=35.0), "3/4 Avant Gauche — Roue 32 Rayons + Châssis Deltabox"),
        (_rn.render_view(sc, azimuth_deg=90.0, elevation_deg=8.0, size=680, fov=34.0), "Profil Droit — Moteur YPVS Plein + Bras Caissonné"),
        (_rn.render_view(sc, azimuth_deg=-90.0, elevation_deg=8.0, size=680, fov=34.0), "Profil Gauche — Allumage + Keihin PWK38 + Pro-Link"),
        (_rn.render_view(sc, azimuth_deg=-132.0, elevation_deg=18.0, size=680, fov=35.0), "3/4 Arrière Gauche — Bras Caissonné & Couronne"),
        (_rn.render_view(sc, azimuth_deg=18.0, elevation_deg=14.0, size=680, fov=35.0), "Face Avant — Fourche KYB SSS & Roue 21 pouces"),
    ]
    _rn.contact_sheet(
        views_full,
        cols=3,
        out_path=str(out_dir / "yamaha_yz125_6views.png"),
        title="Yamaha YZ125 Factory Works v4.1 — 2 Roues 32 Rayons + Châssis Deltabox Caissonné + Moteur YPVS Plein",
    )

    views_engine = [
        (_rn.render_view(sc, azimuth_deg=94.0, elevation_deg=9.0, size=840, fov=16.5), "Côté Droit : Châssis Deltabox + Moteur YPVS Plein + Pot Works Gonflé + Embrayage GYTR"),
        (_rn.render_view(sc, azimuth_deg=-94.0, elevation_deg=9.0, size=840, fov=16.5), "Côté Gauche : Châssis Deltabox + Allumage Or + Cylindre Aileté + Keihin PWK38 + Boîte à Air"),
    ]
    _rn.contact_sheet(
        views_engine,
        cols=2,
        out_path=str(out_dir / "yamaha_yz125_engine_closeup.png"),
        title="Zoom Studio Châssis & Moteur — Zéro Vide, Poutres Deltabox Profilées, Bras Caissonné & Pro-Link",
    )

    rep_stl = json.loads(
        subprocess.check_output(["python3", "scripts/validate.py", "--json", "--max-tris", "120000", str(stl_out)], text=True)
    )
    _pv.build_preview(
        str(out_dir),
        title="Yamaha YZ125 Factory Works v4.1 — Roues 32 Rayons + Châssis Deltabox + Moteur YPVS Plein",
        report=rep_stl,
        glb=str(glb_path),
    )

    dt = time.perf_counter() - t0
    total_tris = sum(int(g.faces.shape[0]) for g in sc.geometry.values())
    print(f"DONE in {dt:.2f}s | total_pbr_tris={total_tris:,} | meshes={len(sc.geometry)}")
    for k, g in sc.geometry.items():
        print(f"   - {k}: {g.faces.shape[0]:,} tris")
    print(f"STL validation: watertight={rep_stl['watertight']} | components={rep_stl['components']} | hard_fail={rep_stl['hard_fail']}")
