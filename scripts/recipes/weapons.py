"""Recette G36 — Heckler & Koch G36 (5,56 × 45 mm) en polymère sable.

Version catalogue de `examples/g36_rifle/build_g36.py` : mêmes cotes, mêmes
pièces, utilisable directement par `turbo_forge.py g36`.
"""
from __future__ import annotations

import math

import numpy as np
import trimesh

import greebles as gr
import meshkit as mk
from .registry import register


MAT_TAN = mk.Material("g36_tan_polymer", "#7d6a46", metallic=0.0, roughness=0.58)
MAT_TAN_DARK = mk.Material("g36_tan_shadow", "#63543a", metallic=0.0, roughness=0.64)
MAT_BLACK = mk.Material("g36_black_polymer", "#191a1d", metallic=0.0, roughness=0.46)
MAT_STEEL = mk.Material("g36_phosphated_steel", "#2e3137", metallic=1.0, roughness=0.42)
MAT_STEEL_BRIGHT = mk.Material("g36_bolt_steel", "#565b63", metallic=1.0, roughness=0.26)
MAT_RUBBER = mk.Material("g36_butt_rubber", "#121214", metallic=0.0, roughness=0.94)
MAT_MAG = mk.Material("g36_mag_polymer", "#1f2124", metallic=0.0, roughness=0.36)
MAT_GLASS = mk.mat.glass("#c8d8dc", opacity=0.22, roughness=0.04)
MAT_RED = mk.mat.emissive("#ff2416", 2.4)

def rrect(hw: float, hh: float, r: float, n: int = 36) -> np.ndarray:
    """Rectangle à coins arrondis, demi-largeur `hw` / demi-hauteur `hh`, CCW."""
    r = float(min(r, hw * 0.98, hh * 0.98))
    seg = max(3, int(n) // 4)
    pts = []
    for cu, cv, a0 in ((hw - r, hh - r, 0.0), (-(hw - r), hh - r, 90.0),
                       (-(hw - r), -(hh - r), 180.0), (hw - r, -(hh - r), 270.0)):
        for k in range(seg):
            a = math.radians(a0 + 90.0 * k / seg)
            pts.append((cu + r * math.cos(a), cv + r * math.sin(a)))
    return np.asarray(pts, dtype=np.float64)


def rounded_poly(pts, r: float, seg: int = 8) -> np.ndarray:
    """Polygone à coins arrondis (quadratique par coin), CCW."""
    pts = np.asarray(pts, dtype=np.float64)
    n = len(pts)
    out = []
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        v0, v1 = p0 - p1, p2 - p1
        l0, l1 = np.linalg.norm(v0), np.linalg.norm(v1)
        rr = min(r, l0 * 0.45, l1 * 0.45)
        a, bb = p1 + v0 / l0 * rr, p1 + v1 / l1 * rr
        for k in range(seg + 1):
            s = (k / seg)
            s = s * s * (3.0 - 2.0 * s)
            out.append((1 - s) ** 2 * a + 2 * (1 - s) * s * p1 + s ** 2 * bb)
    return np.asarray(out)


def loft_y(sections, n: int = 36, caps: bool = True):
    """Loft le long de +Y. `sections` = [(y, demi_largeur_x, z_centre, demi_hauteur_z, rayon)]."""
    rings = []
    for y, hw, zc, hh, r in sections:
        p = rrect(hw, hh, r, n)
        rings.append(np.column_stack([p[:, 0], np.full(len(p), float(y)),
                                      p[:, 1] + float(zc)]))
    return mk.loft(rings, caps=caps)


def ring_perp(center, axis, hw, hh, r, n: int = 32) -> np.ndarray:
    """Anneau arrondi dans le plan perpendiculaire à `axis`."""
    p = rrect(hw, hh, r, n)
    # COPIE obligatoire : `np.asarray` renverrait le tableau de l'appelant et la
    # normalisation en place corromprait le vecteur réutilisé d'une section à l'autre.
    a = np.array(axis, dtype=np.float64, copy=True)
    a /= max(float(np.linalg.norm(a)), 1e-9)
    ex = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(ex, a))) > 0.94:
        ex = np.array([0.0, 0.0, 1.0])
    ey = np.cross(a, ex)
    ey /= max(float(np.linalg.norm(ey)), 1e-9)
    ex = np.cross(ey, a)
    ex /= max(float(np.linalg.norm(ex)), 1e-9)
    c = np.asarray(center, dtype=np.float64)
    return c[None, :] + p[:, 0:1] * ex[None, :] + p[:, 1:2] * ey[None, :]


def prism_x(poly_yz, x0: float, x1: float):
    """Prisme extrudé le long de X depuis un polygone (y, z)."""
    poly = np.asarray(poly_yz, dtype=np.float64)
    rings = [np.column_stack([np.full(len(poly), x), poly[:, 0], poly[:, 1]])
             for x in (float(x0), float(x1))]
    return mk.loft(rings, caps=True)


def oval_cutter(length, half_h, thick, center, tilt_deg=0.0):
    """Lumière oblongue traversant l'axe X (garde-main, crosse)."""
    w = max(float(length), 1e-4)
    r = min(float(half_h), w * 0.5) * 0.98
    p = rrect(w * 0.5, float(half_h), r, 28)
    m = mk.extrude([(float(a), float(b)) for a, b in p], float(thick))
    mk.rot_y(m, 90.0)                       # extrusion : +Z -> +X
    if tilt_deg:
        mk.rot_x(m, float(tilt_deg))
    mk.place(m, float(center[0]), float(center[1]), float(center[2]))
    return m


def loft_y_fn(y0: float, y1: float, n: int, profile, n_ring: int = 36):
    """Loft le long de +Y en échantillonnant `profile(y) -> (hw, zc, hh, r)`.

    Indispensable autour des découpes CSG : un loft à 6 sections ne laisse que de
    grandes faces, et la découpe d'une lumière les retriangule en gros triangles
    dont les normales lissées produisent des traînées visibles.
    """
    ys = np.linspace(float(y0), float(y1), int(n))
    rings = []
    for y in ys:
        hw, zc, hh, r = profile(float(y))
        p = rrect(hw, hh, r, n_ring)
        rings.append(np.column_stack([p[:, 0], np.full(len(p), float(y)),
                                      p[:, 1] + float(zc)]))
    return mk.loft(rings, caps=True)


def crisp(mesh):
    """Normales de facettes sur une pièce usinée.

    `renderer._gather` lisse une arête dès que `dot(vnormale, normale_face) > 0.72`
    sur les 3 sommets. Autour des lumières du garde-main, cela faisait baver la
    lumière sur les cloisons (traînées grises). On duplique les sommets pour que
    chaque face porte sa propre normale : les arêtes redeviennent nettes.
    """
    m = mesh.copy()
    m.unmerge_vertices()          # opère EN PLACE (retourne None)
    # `unmerge_vertices` fusionne les sommets confondus par tolérance : les faces
    # coplanaires issues du CSG peuvent alors laisser des arêtes ouvertes.
    if not m.is_watertight:
        m.merge_vertices()        # on repasse en soudé pour retrouver l'étanchéité
        trimesh.repair.fill_holes(m)
    return m


# --------------------------------------------------------------------------- #
# Cotes maîtresses (mètres) — axe du canon à z = 0
# --------------------------------------------------------------------------- #
RECV_LO, RECV_HI = -0.246, 0.236          # longueur du boîtier
RECV_TOP = 0.0305                          # dessus du boîtier (assise du pontet)
RAIL_TOP = 0.0578                          # dessus du pontet (base des dents)
RECV_HW = 0.0250


def build_g36() -> mk.Builder:
    b = mk.Builder("g36_rifle")

    # ------------------------------------------------------------------ #
    # 1. Boîtier (receiver) — loft continu, arêtes arrondies
    # ------------------------------------------------------------------ #
    receiver = loft_y([
        (RECV_LO, 0.0215, -0.0035, 0.0295, 0.008),
        (-0.205, 0.0236, -0.0035, 0.0315, 0.009),
        (-0.140, 0.0248, -0.0035, 0.0325, 0.010),
        (-0.060, RECV_HW, -0.0035, 0.0330, 0.010),
        ( 0.030, RECV_HW, -0.0035, 0.0330, 0.010),
        ( 0.120, 0.0246, -0.0035, 0.0322, 0.010),
        ( 0.195, 0.0238, -0.0035, 0.0310, 0.009),
        (RECV_HI, 0.0228, -0.0035, 0.0295, 0.008),
    ])
    b.add(receiver, MAT_TAN, name="receiver")

    # ------------------------------------------------------------------ #
    # 2. Pontet-rail : bloc surélevé + fenêtre triangulaire de délestage
    # ------------------------------------------------------------------ #
    bridge = loft_y([
        (RECV_LO, 0.0128, 0.0442, 0.0138, 0.005),
        (-0.215, 0.0140, 0.0446, 0.0140, 0.005),
        (-0.120, 0.0146, 0.0448, 0.0140, 0.005),
        ( 0.000, 0.0146, 0.0448, 0.0140, 0.005),
        ( 0.120, 0.0144, 0.0446, 0.0138, 0.005),
        ( 0.205, 0.0138, 0.0440, 0.0134, 0.005),
        (RECV_HI, 0.0126, 0.0430, 0.0126, 0.004),
    ])
    # Fenêtre triangulaire : base au ras du boîtier, pointe vers l'avant
    # La fenêtre ne doit PAS manger la barre : on garde ~7 mm de matière en haut
    # et ~6 mm en bas, sinon le rail paraît flotter au-dessus du boîtier.
    window = prism_x(rounded_poly([(-0.118, 0.0368), (0.074, 0.0368),
                                   (0.040, 0.0500)], 0.008, 8), -0.030, 0.030)
    bridge = mk.difference(bridge, [window])
    b.add(crisp(bridge), MAT_TAN, name="rail_bridge")

    # Renfort d'assise : sans lui la lumière triangulaire laissait voir le vide
    # entre le dessus du boîtier et la barre du pontet.
    for yy in (-0.222, 0.176):
        post = mk.rounded_box(0.0262, 0.0165, 0.0165, r=0.004)
        mk.place(post, 0.0, yy, 0.0300)
        b.add(post, MAT_TAN, name=f"rail_bridge_post_{'rear' if yy < 0 else 'front'}")

    rail = gr.picatinny_rail(length=0.474, width=0.0200, height=0.0125, teeth=18)
    mk.place(rail, 0.0, -0.240, RAIL_TOP)
    b.add(rail, MAT_BLACK, name="top_rail")

    # ------------------------------------------------------------------ #
    # 3. Viseur point rouge intégré (version export)
    # ------------------------------------------------------------------ #
    body = loft_y([
        (-0.242, 0.0150, 0.0850, 0.0170, 0.007),
        (-0.222, 0.0160, 0.0862, 0.0182, 0.008),
        (-0.176, 0.0160, 0.0866, 0.0182, 0.008),
        (-0.156, 0.0142, 0.0852, 0.0158, 0.006),
    ])
    b.add(body, MAT_BLACK, name="red_dot_housing")

    # Pied de montage sur le rail
    mount = loft_y([
        (-0.226, 0.0140, 0.0715, 0.0056, 0.002),
        (-0.176, 0.0140, 0.0715, 0.0056, 0.002),
    ])
    b.add(mount, MAT_BLACK, name="red_dot_mount")

    # Tube oculaire (arrière) et objectif (avant)
    for tag, yy, r_out, r_in in (("eyepiece", -0.252, 0.0142, 0.0112),
                                 ("objective", -0.150, 0.0152, 0.0114)):
        t = mk.tube(r_out, r_in, 0.016, sections=40)
        mk.rot_x(t, -90.0)
        mk.place(t, 0.0, yy, 0.0862)
        b.add(t, MAT_BLACK, name=f"red_dot_{tag}")

    glass = mk.cylinder(0.0110, 0.0016, sections=40)
    mk.rot_x(glass, -90.0)
    mk.place(glass, 0.0, -0.1600, 0.0862)
    b.add(glass, MAT_GLASS, name="red_dot_lens")

    dot = mk.cylinder(0.0020, 0.0012, sections=24)
    mk.rot_x(dot, -90.0)
    mk.place(dot, 0.0, -0.1645, 0.0862)
    b.add(dot, MAT_RED, name="red_dot_reticle")

    # Mollettes de réglage (dessus + flanc droit)
    elev = mk.cylinder(0.0086, 0.0070, sections=26)
    mk.place(elev, 0.0, -0.199, 0.1035)
    b.add(elev, MAT_BLACK, name="red_dot_knob_elev")
    wind = mk.cylinder(0.0074, 0.0064, sections=26)
    mk.rot_y(wind, -90.0)
    mk.place(wind, 0.0186, -0.199, 0.0862)
    b.add(wind, MAT_BLACK, name="red_dot_knob_wind")

    # ------------------------------------------------------------------ #
    # 4. Crosse pleine + plaque de couche + fente de grenadière
    # ------------------------------------------------------------------ #
    st_keys = [
        (RECV_LO, 0.0218, -0.0035, 0.0295, 0.008),
        (-0.268, 0.0216, -0.0075, 0.0330, 0.008),
        (-0.310, 0.0212, -0.0135, 0.0380, 0.009),
        (-0.355, 0.0208, -0.0195, 0.0425, 0.009),
        (-0.400, 0.0204, -0.0245, 0.0462, 0.010),
        (-0.440, 0.0202, -0.0280, 0.0486, 0.010),
        (-0.462, 0.0200, -0.0295, 0.0496, 0.010),
    ]
    st_y = np.array([k[0] for k in st_keys])
    st_v = np.array([k[1:] for k in st_keys])

    def st_profile(y):
        return tuple(np.interp(y, st_y, st_v[:, k]) for k in range(4))

    stock = loft_y_fn(-0.462, RECV_LO, 34, st_profile)
    sling_slot = oval_cutter(length=0.020, half_h=0.0040, thick=0.060,
                             center=(0.0, -0.392, -0.0270), tilt_deg=-9.0)
    stock = mk.difference(stock, [sling_slot])
    b.add(crisp(stock), MAT_TAN, name="stock")

    butt = loft_y([
        (-0.484, 0.0198, -0.0300, 0.0500, 0.013),
        (-0.474, 0.0206, -0.0296, 0.0510, 0.014),
        (-0.462, 0.0200, -0.0292, 0.0494, 0.012),
    ])
    b.add(butt, MAT_RUBBER, name="butt_pad")

    # Renfort de poignée de crosse (le G36 a une arête marquée sous la crosse)
    rib = loft_y([
        (-0.470, 0.0180, -0.0620, 0.0060, 0.003),
        (-0.400, 0.0180, -0.0560, 0.0060, 0.003),
        (-0.330, 0.0176, -0.0470, 0.0055, 0.003),
        (-0.266, 0.0170, -0.0370, 0.0050, 0.003),
    ])
    b.add(rib, MAT_TAN_DARK, name="stock_belly_rib")

    # ------------------------------------------------------------------ #
    # 5. Poignée pistolet (inclinée), pontet, détente, sélecteurs
    # ------------------------------------------------------------------ #
    g_top = np.array([0.0, -0.166, -0.0260])
    g_bot = np.array([0.0, -0.222, -0.1330])
    # Le G36 a une poignée TRAPUE à section quasi constante : la varier jusqu'à une
    # pointe donnait une lame de couteau. On garde 30 mm d'épaisseur jusqu'en bas et
    # on ferme par un bouchon plat chanfreiné.
    prof = [(0.0158, 0.0218), (0.0160, 0.0220), (0.0158, 0.0218), (0.0154, 0.0214),
            (0.0150, 0.0208), (0.0146, 0.0202), (0.0143, 0.0197), (0.0141, 0.0193)]
    grip_rings = []
    for t, (hw, hh) in zip(np.linspace(0.0, 1.0, len(prof)), prof):
        c = g_top * (1.0 - t) + g_bot * t
        c = c + np.array([0.0, 0.0050 * math.sin(math.pi * t), 0.0])
        grip_rings.append(ring_perp(c, g_bot - g_top, hw, hh, 0.0075, 32))
    axis = g_bot - g_top
    axis = axis / np.linalg.norm(axis)
    # Bouchon : 8 mm de matière pleine, chanfreiné
    for dz, sc_ in ((0.0035, 0.985), (0.0090, 0.88)):
        grip_rings.append(ring_perp(g_bot + axis * dz, axis,
                                   0.0141 * sc_, 0.0193 * sc_, 0.0075 * sc_, 32))
    b.add(mk.loft(grip_rings, caps=True), MAT_TAN, name="pistol_grip")

    # Stries de préhension sur la face avant de la poignée
    fg = []
    for k in range(4):
        t = 0.30 + 0.16 * k
        c = g_top * (1.0 - t) + g_bot * t
        rib = mk.rounded_box(0.0290, 0.0040, 0.0044, r=0.0016)
        mk.rot_x(rib, -math.degrees(math.atan2(axis[1], -axis[2])) * 0.55)
        mk.place(rib, 0.0, c[1] - 0.0165, c[2] + 0.0015)
        fg.append(rib)
    b.add(mk.union(fg), MAT_TAN_DARK, name="pistol_grip_serrations")

    # Pontet : PLAQUE pleine extrudée sur 11 mm. Construit en `tube_sweep` il
    # ressemblait à un cintre ; le G36 a un pontet massif moulé avec la poignée.
    guard_poly = rounded_poly([
        (0.000, -0.0330), (0.000, -0.0250), (0.030, -0.0210),
        (0.062, -0.0270), (0.076, -0.0480), (0.068, -0.0830),
        (0.030, -0.0910), (-0.020, -0.0860), (-0.046, -0.0610),
    ], 0.006, 8)
    guard_poly[:, 0] -= 0.150            # recentrage sur la zone détente
    guard = prism_x(guard_poly, -0.0055, 0.0055)
    b.add(guard, MAT_TAN, name="trigger_guard")

    # Détente : lame plate cintrée (pas un fil)
    trig_poly = rounded_poly([(-0.0085, -0.0300), (0.0085, -0.0300),
                              (0.0085, -0.0520), (-0.0010, -0.0670),
                              (-0.0085, -0.0640), (-0.0085, -0.0480)], 0.0022, 6)
    trig_poly = trig_poly + np.array([-0.1400, 0.0])
    trig = prism_x(trig_poly, -0.0030, 0.0030)
    b.add(trig, MAT_STEEL_BRIGHT, name="trigger")

    for side, tag in ((1, "right"), (-1, "left")):
        sel = mk.cylinder(0.0070, 0.0078, sections=22)
        mk.rot_y(sel, 90.0)
        mk.place(sel, side * 0.0252, -0.148, -0.010)
        b.add(sel, MAT_BLACK, name=f"fire_selector_{tag}")
        # Levier partant du pivot vers l'arrière-bas (position « sûr »), prolongé
        # d'un palonnier : un pavé isolé flottait à côté du sélecteur.
        lev = mk.tube_sweep(
            [(side * 0.0268, -0.1480, -0.0100),
             (side * 0.0268, -0.1620, -0.0175),
             (side * 0.0268, -0.1730, -0.0215)],
            r=0.0038, sections=12, smooth_pts=16,
        )
        b.add(lev, MAT_BLACK, name=f"fire_selector_lever_{tag}")

    mag_rel = mk.rounded_box(0.011, 0.009, 0.006, r=0.0026)
    mk.place(mag_rel, -0.0286, -0.036, -0.020)
    b.add(mag_rel, MAT_BLACK, name="mag_release")

    # ------------------------------------------------------------------ #
    # 6. Puits de chargeur + chargeur courbe
    # ------------------------------------------------------------------ #
    # Puits de chargeur : descendre franchement du boîtier, section légèrement
    # plus étroite que lui et inclinée vers l'avant. Un `loft` large donnait un
    # « blob » suspendu sous l'arme.
    well = loft_y([
        (-0.080, 0.0230, -0.0320, 0.0075, 0.003),
        (-0.062, 0.0244, -0.0368, 0.0125, 0.005),
        (-0.040, 0.0248, -0.0398, 0.0155, 0.006),
        (-0.014, 0.0248, -0.0408, 0.0162, 0.006),
        ( 0.014, 0.0244, -0.0398, 0.0155, 0.006),
        ( 0.038, 0.0238, -0.0368, 0.0125, 0.005),
        ( 0.056, 0.0230, -0.0320, 0.0075, 0.003),
    ])
    b.add(well, MAT_TAN_DARK, name="magazine_well")

    # Courbe du chargeur : plonge vers l'avant (y+) en descendant
    def mag_point(t: float) -> np.ndarray:
        return np.array([0.0, -0.012 + 0.080 * (t ** 1.65), -0.050 - 0.152 * t])

    mag_rings = []
    mag_n = 13
    for i in range(mag_n):
        t = i / (mag_n - 1)
        c = mag_point(t)
        d = (mag_point(min(t + 0.08, 1.0)) - mag_point(max(t - 0.08, 0.0)))
        hw = 0.0150 - 0.0010 * t
        hh = 0.0208 - 0.0010 * t
        mag_rings.append(ring_perp(c, d, hw, hh, 0.0065, 30))
    # Semelle débordante (élargissement final)
    c_end = mag_point(1.0)
    d_end = mag_point(1.0) - mag_point(0.94)
    mag_rings.append(ring_perp(c_end + d_end * 0.055, d_end, 0.0166, 0.0224, 0.007, 30))
    mag_rings.append(ring_perp(c_end + d_end * 1.25, d_end, 0.0158, 0.0214, 0.007, 30))
    b.add(mk.loft(mag_rings, caps=True), MAT_MAG, name="magazine")

    # Nervures de préhension du chargeur
    ribs = []
    for k in range(3):
        t = 0.22 + 0.20 * k
        c = mag_point(t)
        d = mag_point(min(t + 0.08, 1.0)) - mag_point(max(t - 0.08, 0.0))
        ang = math.degrees(math.atan2(d[1], -d[2]))
        rb = mk.rounded_box(0.0312, 0.0034, 0.0062, r=0.0015)
        mk.rot_x(rb, -ang)
        mk.place(rb, 0.0, c[1], c[2])
        ribs.append(rb)
    b.add(mk.union(ribs), MAT_BLACK, name="magazine_ribs")

    # ------------------------------------------------------------------ #
    # 7. Garde-main ventilé + rails
    # ------------------------------------------------------------------ #
    hg_keys = [
        (0.212, 0.0230, -0.0040, 0.0298, 0.009),
        (0.232, 0.0258, -0.0055, 0.0312, 0.011),
        (0.290, 0.0264, -0.0068, 0.0316, 0.012),
        (0.352, 0.0258, -0.0070, 0.0304, 0.012),
        (0.394, 0.0240, -0.0076, 0.0272, 0.010),
        (0.408, 0.0222, -0.0076, 0.0238, 0.009),
    ]
    hg_y = np.array([k[0] for k in hg_keys])
    hg_v = np.array([k[1:] for k in hg_keys])

    def hg_profile(y):
        return tuple(np.interp(y, hg_y, hg_v[:, k]) for k in range(4))

    handguard = loft_y_fn(0.212, 0.408, 40, hg_profile)
    cutters = []
    for side in (-1, 1):
        for k, (yy, ln) in enumerate(((0.258, 0.056), (0.316, 0.050), (0.368, 0.038))):
            # Traversant de part en part : sur un vrai G36 on VOIT À TRAVERS les
            # évents. Un perçage partiel ne faisait qu'une cuvette sombre.
            cutters.append(oval_cutter(length=ln, half_h=0.0102, thick=0.090,
                                       center=(0.0, yy, 0.0012),
                                       tilt_deg=7.0))
    handguard = mk.difference(handguard, cutters)
    b.add(crisp(handguard), MAT_TAN, name="handguard")

    hg_rail = gr.picatinny_rail(length=0.152, width=0.0200, height=0.0115, teeth=6)
    mk.place(hg_rail, 0.0, 0.234, -0.0470)
    b.add(hg_rail, MAT_BLACK, name="handguard_rail_bottom")

    # Placé SOUS les évents : un rail au milieu du flanc cachait les trois lumières.
    side_rail = gr.picatinny_rail(length=0.092, width=0.0165, height=0.0092, teeth=4)
    mk.rot_y(side_rail, -90.0)          # les dents pointent vers +X
    mk.place(side_rail, 0.0232, 0.300, -0.0345)
    b.add(side_rail, MAT_BLACK, name="handguard_rail_side")

    sling = mk.torus(0.0130, 0.0032, major=30, minor=10)
    mk.rot_y(sling, 90.0)
    mk.place(sling, 0.0215, 0.358, -0.0410)
    b.add(sling, MAT_STEEL, name="front_sling_loop")

    # ------------------------------------------------------------------ #
    # 8. Canon, bloc de gaz, hausse à ailes, flash-hider
    # ------------------------------------------------------------------ #
    barrel = mk.cylinder(0.0094, 0.100, sections=28)
    mk.rot_x(barrel, -90.0)
    mk.place(barrel, 0.0, 0.398, 0.0)
    b.add(barrel, MAT_STEEL, name="barrel")

    gas_block = loft_y([
        (0.384, 0.0130, 0.0060, 0.0180, 0.005),
        (0.396, 0.0142, 0.0065, 0.0196, 0.006),
        (0.424, 0.0142, 0.0065, 0.0196, 0.006),
        (0.438, 0.0126, 0.0058, 0.0168, 0.005),
    ])
    b.add(gas_block, MAT_STEEL, name="gas_block")

    # Hausse : socle + ailes de protection + guidon
    sight_base = loft_y([
        (0.390, 0.0092, 0.0245, 0.0130, 0.004),
        (0.408, 0.0094, 0.0290, 0.0175, 0.004),
        (0.426, 0.0090, 0.0272, 0.0158, 0.004),
    ])
    b.add(sight_base, MAT_STEEL, name="front_sight_base")

    wings = []
    for sx in (-1, 1):
        w = mk.rounded_box(0.0034, 0.032, 0.024, r=0.0016)
        mk.place(w, sx * 0.0102, 0.392, 0.0250)
        wings.append(w)
    b.add(mk.union(wings), MAT_STEEL, name="front_sight_wings")

    post = mk.cylinder(0.0018, 0.0150, sections=16)
    mk.place(post, 0.0, 0.408, 0.0430)
    b.add(post, MAT_STEEL_BRIGHT, name="front_sight_post")

    # Flash-hider à dents (birdcage) : tube creux + fentes rayonnantes
    fh = mk.tube(0.0116, 0.0082, 0.048, sections=32)
    mk.rot_x(fh, -90.0)
    mk.place(fh, 0.0, 0.456, 0.0)
    fh_cuts = []
    for k in range(6):
        ang = -75.0 + 30.0 * k
        c = mk.box(0.0026, 0.024, 0.034)
        mk.rot_x(c, float(ang))
        mk.place(c, 0.0, 0.484, 0.0)
        fh_cuts.append(c)
    fh = mk.difference(fh, fh_cuts)
    b.add(fh, MAT_STEEL, name="flash_hider")

    # Bague de baïonnette sous le flash-hider
    lug = mk.rounded_box(0.010, 0.020, 0.014, r=0.003)
    mk.place(lug, 0.0, 0.442, -0.0135)
    b.add(lug, MAT_STEEL, name="bayonet_lug")

    # ------------------------------------------------------------------ #
    # 9. Poignée d'armement (+X), fenêtre d'éjection et déflecteur (-X)
    # ------------------------------------------------------------------ #
    stem = loft_y([
        (0.148, 0.0110, 0.0120, 0.0090, 0.003),
        (0.180, 0.0110, 0.0124, 0.0094, 0.003),
    ])
    mk.place(stem, 0.0225, 0.0, 0.0)
    b.add(stem, MAT_BLACK, name="charging_handle_stem")

    knob = mk.capsule(0.0078, 0.030, sections=24)
    mk.rot_x(knob, -90.0)
    mk.place(knob, 0.0355, 0.164, 0.0120)
    b.add(knob, MAT_BLACK, name="charging_handle_knob")

    port = mk.rounded_box(0.005, 0.064, 0.027, r=0.004)
    mk.place(port, -0.0238, 0.026, 0.0035)
    b.add(port, MAT_STEEL, name="ejection_port")

    deflector = mk.rounded_box(0.0038, 0.052, 0.0062, r=0.0018)
    mk.rot_y(deflector, 16.0)
    mk.place(deflector, -0.0288, 0.028, 0.0185)
    b.add(deflector, MAT_BLACK, name="brass_deflector")

    # ------------------------------------------------------------------ #
    # 10. Détails mécaniques : axes, vis, stries, grenadière arrière
    # ------------------------------------------------------------------ #
    pins = []
    for yy in (-0.198, -0.130, 0.190, 0.124):
        p = mk.cylinder(0.0040, 0.0512, sections=18)
        mk.rot_y(p, 90.0)
        mk.place(p, 0.0255, yy, -0.0075)
        pins.append(p)
    b.add(mk.union(pins), MAT_STEEL, name="receiver_pins")

    bolts = []
    for yy in (-0.058, 0.062):
        bl = gr.hex_bolt(r=0.0054, h=0.0042)
        mk.rot_y(bl, 90.0)
        mk.place(bl, -0.0252, yy, 0.0125)
        bolts.append(bl)
    b.add(mk.union(bolts), MAT_STEEL_BRIGHT, name="receiver_bolts")

    serr = []
    for k in range(6):
        rb = mk.rounded_box(0.0035, 0.0030, 0.021, r=0.0012)
        mk.place(rb, 0.0, -0.232 + 0.0072 * k, 0.0040)
        serr.append(rb)
    b.add(mk.union(serr), MAT_TAN_DARK, name="receiver_serrations")

    # Grenadière arrière (boucle sous la crosse)
    rear_sling = mk.torus(0.0115, 0.0030, major=26, minor=10)
    mk.rot_y(rear_sling, 90.0)
    mk.place(rear_sling, 0.0, -0.252, -0.0420)
    b.add(rear_sling, MAT_STEEL, name="rear_sling_loop")

    # ------------------------------------------------------------------ #
    # 11. Sockets gameplay
    # ------------------------------------------------------------------ #
    b.def_socket("SOCKET_muzzle", pos=(0.0, 0.500, 0.0))
    b.def_socket("SOCKET_grip", pos=(0.0, -0.200, -0.090))
    b.def_socket("SOCKET_optic", pos=(0.0, -0.199, 0.1035))
    b.def_socket("SOCKET_eject", pos=(-0.030, 0.026, 0.008))
    b.def_socket("SOCKET_mag", pos=(0.0, 0.030, -0.200))
    b.def_socket("SOCKET_rail_top", pos=(0.0, -0.020, 0.0680))
    b.def_socket("SOCKET_rail_bottom", pos=(0.0, 0.310, -0.0585))

    return b




@register("g36",
          defaults={},
          info=[{"name": "n/a", "type": "str", "help": "Aucun paramètre : cotes réelles fixes (998 mm)"}])
def build_g36_registered() -> mk.Builder:
    """G36 complet, posé au sol, avec sockets gameplay (`muzzle`, `grip`, `optic`...)."""
    b = build_g36()
    lo = min(float(p[0].bounds[0][2]) for p in b.parts)
    for mesh, _mat, _lbl in b._parts:
        mesh.apply_translation([0.0, 0.0, -lo])
    for sname in b._sockets:
        b._sockets[sname]["position"][2] -= lo
    return b
