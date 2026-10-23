#!/usr/bin/env python3
"""
G36E — Heckler & Koch G36 version export, construction **hard-surface**.

Méthode (c'est le cœur du problème précédent)
---------------------------------------------
La v1 était entièrement faite de `rrect()` loftés avec un rayon de **10 mm sur
un boîtier de 42 mm** : 40 % de chaque flanc était arrondi, donc aucun plan,
aucune arête, aucune ligne de lumière -> un savon. Ici :

1. **Silhouette** : profil anguleux en (y, z) extrudé le long de X.
2. **Section** : rectangle **chanfreiné** en (x, z) extrudé le long de Y.
3. `intersection` des deux : le corps prend la bonne silhouette ET la bonne
   section, avec des chanfreins de 2 mm qui courent sur toute la longueur.

Un chanfrein à 45° sépare deux faces de `cos(45°) = 0.707 < 0.72`, le seuil de
lissage de `renderer._gather` : les arêtes restent **franches** sans avoir à
dupliquer un seul sommet. C'est ce qui donne le rendu métallique/polymère.

Cotes relevées sur une vue de profil (L/H mesuré = 3.40, réel = 3.50) :
  longueur 998 mm · axe du canon à 32 % de la hauteur · poignée de transport de
  40 % à 70 % de la longueur · crosse squelette ajourée · chargeur courbe.

Conventions : Z haut, tir vers +Y, profil depuis +X, axe du canon à z = 0.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "scripts"))

import greebles as gr  # noqa: E402
import meshkit as mk  # noqa: E402

# --------------------------------------------------------------------------- #
# Matières — relevées sur la photo : polymère anthracite, crosse/grip noirs
# --------------------------------------------------------------------------- #
MAT_POLY = mk.Material("g36_polymer", "#191d20", metallic=0.0, roughness=0.58)
MAT_POLY_DK = mk.Material("g36_polymer_dark", "#101315", metallic=0.0, roughness=0.62)
MAT_BLACK = mk.Material("g36_black_polymer", "#0c0d0f", metallic=0.0, roughness=0.46)
MAT_STEEL = mk.Material("g36_phosphated", "#24272b", metallic=1.0, roughness=0.42)
MAT_STEEL_DK = mk.Material("g36_phosphate_dark", "#121417", metallic=1.0, roughness=0.50)
MAT_BRIGHT = mk.Material("g36_bare_steel", "#5c6268", metallic=1.0, roughness=0.25)
MAT_RUBBER = mk.Material("g36_rubber", "#08090a", metallic=0.0, roughness=0.95)
MAT_MAG = mk.Material("g36_mag", "#15181b", metallic=0.0, roughness=0.35)
MAT_GLASS = mk.mat.glass("#c8d8dc", opacity=0.20, roughness=0.03)
MAT_RED = mk.mat.emissive("#ff2010", 2.6)
# --------------------------------------------------------------------------- #
# Primitives hard-surface
# --------------------------------------------------------------------------- #
def chamfer_rect(hw: float, hh: float, c: float) -> np.ndarray:
    """Rectangle CHANFREINÉ (octogone) : 4 faces planes + 4 chanfreins à 45°.

    C'est la section d'un boîtier en polymère moulé. Contrairement à un congé
    rayonné, elle laisse de grandes faces planes qui captent la lumière et des
    arêtes nettes qui les séparent.
    """
    hw, hh, c = float(hw), float(hh), float(min(c, hw * 0.9, hh * 0.9))
    return np.array([
        ( hw - c,  hh), ( hw,  hh - c), ( hw, -hh + c), ( hw - c, -hh),
        (-hw + c, -hh), (-hw, -hh + c), (-hw,  hh - c), (-hw + c,  hh),
    ], dtype=np.float64)


# Mapping des plans :
#   prism_x : profil (y, z) extrudé le long de X
#   prism_y : section (x, z) extrudée le long de Y
_M_X = np.array([[0, 0, 1, 0],
                 [1, 0, 0, 0],
                 [0, 1, 0, 0],
                 [0, 0, 0, 1]], dtype=np.float64)      # (a,b,t) -> (t, a, b)
_M_Y = np.array([[1, 0, 0, 0],
                 [0, 0, 1, 0],
                 [0, 1, 0, 0],
                 [0, 0, 0, 1]], dtype=np.float64)      # (a,b,t) -> (a, t, b)


def _extrude2d(points2d, thickness: float, xform: np.ndarray,
               offset: np.ndarray) -> trimesh.Trimesh:
    """Extrusion d'un polygone 2D, **non convexe compris**.

    `mk.loft` ferme ses extrémités par un éventail depuis le barycentre : juste
    pour un convexe, faux pour tout le reste (l'arche de poignée et la crosse
    ajourée ressortaient en ailes de papillon). `mk.extrude` passe par la
    triangulation shapely/earcut, donc n'importe quel contour passe.
    """
    m = mk.extrude([(float(a), float(b)) for a, b in points2d], float(thickness))
    m.apply_transform(xform)
    m.apply_translation(offset)
    return m


def prism_x(poly_yz, x0: float, x1: float) -> trimesh.Trimesh:
    """Profil (y, z) extrudé le long de X, entre x0 et x1."""
    return _extrude2d(poly_yz, abs(float(x1) - float(x0)), _M_X,
                      np.array([float(min(x0, x1)), 0.0, 0.0]))


def prism_y(poly_xz, y0: float, y1: float) -> trimesh.Trimesh:
    """Section (x, z) extrudée le long de Y, entre y0 et y1."""
    return _extrude2d(poly_xz, abs(float(y1) - float(y0)), _M_Y,
                      np.array([0.0, float(min(y0, y1)), 0.0]))


def shell(side_yz, hw: float, zc: float, hh: float, ch: float,
          y0: float, y1: float) -> trimesh.Trimesh:
    """Corps hard-surface = silhouette anguleuse ∩ section chanfreinée."""
    a = prism_x(side_yz, -hw * 1.5, hw * 1.5)
    cs = chamfer_rect(hw, hh, ch)
    cs = cs + np.array([0.0, zc])
    b = prism_y(cs, y0, y1)
    return mk.intersection(a, b)


def ring_ch(center, axis, hw, hh, ch, n_ring: int = 8) -> np.ndarray:
    """Anneau chanfreiné perpendiculaire à `axis`."""
    p = chamfer_rect(hw, hh, ch)
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


# --------------------------------------------------------------------------- #
# Cotes maîtresses (m) — relevées au pixel sur la vue de profil
# --------------------------------------------------------------------------- #
Y_MUZZLE = 0.499
Y_FH_R = 0.448          # base du cache-flammes
Y_HG_F = 0.318          # garde-main avant
Y_HG_R = 0.146          # garde-main arrière
Y_RECV_R = -0.238       # boîtier arrière / charnière de crosse
Y_BUTT = -0.499

Z_HG_T = 0.039          # dessus du garde-main
Z_RC_T = 0.034          # dessus du boîtier (sous l'arche)
Z_BODY_B = -0.031       # dessous commun (garde-main + boîtier)
Z_ARCH_T = 0.100        # sommet de la poignée de transport
Z_OPTIC_T = 0.094       # sommet du bloc optique

HW_HG = 0.029           # demi-largeur garde-main (58 mm)
HW_RC = 0.031           # demi-largeur boîtier (62 mm)
CH = 0.0022             # chanfrein : la clé du rendu hard-surface


def build() -> mk.Builder:
    """G36E — une pièce = un bloc extrudé, cotes mesurées sur la photo."""
    b = mk.Builder("g36_rifle")

    # ================================================================== #
    # 1. GARDE-MAIN — plus haut que le boîtier (marche mesurée de 5 mm)
    # ================================================================== #
    hg_side = [
        (0.318, Z_HG_T), (0.318, -0.022), (0.306, Z_BODY_B),
        (Y_HG_R, Z_BODY_B), (Y_HG_R, Z_HG_T),
    ]
    hg = shell(hg_side, HW_HG, (Z_HG_T + Z_BODY_B) / 2, (Z_HG_T - Z_BODY_B) / 2,
               CH, Y_HG_R, Y_HG_F)
    # 6 lumières oblongues par flanc (20-32 % de la longueur), fraisées à 5 mm
    vents = []
    for k in range(6):
        yy = 0.286 - 0.0225 * k
        for sx in (-1, 1):
            v = mk.box(0.012, 0.0105, 0.0140)
            mk.place(v, sx * (HW_HG - 0.0030), yy, 0.0090)
            vents.append(v)
    hg = mk.difference(hg, vents)
    b.add(hg, MAT_POLY, name="handguard")
    core = mk.box(2 * (HW_HG - 0.010), 0.190, 0.0300)
    mk.place(core, 0.0, 0.238, 0.001)
    b.add(core, MAT_POLY_DK, name="handguard_core")

    # ================================================================== #
    # 2. BOÎTIER — dessus 5 mm plus bas que le garde-main
    # ================================================================== #
    rc_side = [
        (Y_HG_R, Z_RC_T), (Y_HG_R, Z_BODY_B),
        (-0.220, Z_BODY_B), (-0.232, -0.020), (Y_RECV_R, -0.004), (Y_RECV_R, Z_RC_T),
    ]
    rc = shell(rc_side, HW_RC, (Z_RC_T + Z_BODY_B) / 2, (Z_RC_T - Z_BODY_B) / 2,
               CH, Y_RECV_R, Y_HG_R)
    b.add(rc, MAT_POLY, name="receiver")

    # ================================================================== #
    # 3. POIGNÉE DE TRANSPORT — fenêtre mesurée 181 × 54 mm
    # ================================================================== #
    handle_outer = [
        (Y_HG_R, Z_RC_T), (Y_HG_R, 0.056), (0.056, Z_ARCH_T),
        (-0.097, Z_ARCH_T), (-0.097, 0.086), (0.070, 0.086), (0.108, Z_RC_T),
    ]
    b.add(prism_x(handle_outer, -0.0090, 0.0090), MAT_POLY, name="carry_handle")

    # ================================================================== #
    # 4. BLOC OPTIQUE — 68 mm de haut, sommet 6 mm sous l'arche
    # ================================================================== #
    optic_side = [
        (-0.097, Z_RC_T), (-0.097, Z_OPTIC_T), (-0.196, Z_OPTIC_T),
        (-0.210, 0.087), (-0.224, 0.048), (Y_RECV_R, 0.041), (Y_RECV_R, Z_RC_T),
    ]
    b.add(shell(optic_side, 0.0190, (Z_OPTIC_T + Z_RC_T) / 2,
                (Z_OPTIC_T - Z_RC_T) / 2, CH, Y_RECV_R, -0.097),
          MAT_POLY, name="optic_housing")
    # lentille frontale encastrée + oculaire + tourelle
    ob = mk.cylinder(0.0142, 0.0030, sections=30)
    mk.rot_x(ob, -90.0)
    mk.place(ob, 0.0, -0.0975, 0.0655)
    b.add(ob, MAT_POLY_DK, name="optic_objective_ring")
    lens = mk.cylinder(0.0118, 0.0026, sections=30)
    mk.rot_x(lens, -90.0)
    mk.place(lens, 0.0, -0.0995, 0.0655)
    b.add(lens, MAT_GLASS, name="optic_lens")
    eye = mk.cylinder(0.0128, 0.0032, sections=28)
    mk.rot_x(eye, -90.0)
    mk.place(eye, 0.0, -0.2210, 0.0655)
    b.add(eye, MAT_POLY_DK, name="optic_ocular")
    dot = mk.cylinder(0.0018, 0.0012, sections=16)
    mk.rot_x(dot, -90.0)
    mk.place(dot, 0.0, -0.2190, 0.0655)
    b.add(dot, MAT_RED, name="optic_reticle")
    kt = mk.cylinder(0.0078, 0.0070, sections=22)
    mk.place(kt, 0.0, -0.150, Z_OPTIC_T)
    b.add(kt, MAT_BLACK, name="optic_knob_top")
    ks = mk.cylinder(0.0074, 0.0062, sections=22)
    mk.rot_y(ks, 90.0)
    mk.place(ks, 0.0195, -0.150, 0.0660)
    b.add(ks, MAT_BLACK, name="optic_knob_side")

    # ================================================================== #
    # 5. CROSSE SQUELETTE — fenêtre mesurée (y -325..-444, z +13..-40)
    # ================================================================== #
    stock_side = [
        (Y_RECV_R, 0.041), (-0.253, 0.034), (-0.281, 0.025), (-0.394, 0.024),
        (-0.437, 0.024), (-0.480, 0.025), (Y_BUTT, -0.001),
        (Y_BUTT, -0.127), (-0.482, -0.127), (-0.465, -0.120), (-0.451, -0.104),
        (-0.437, -0.076), (-0.423, -0.062), (-0.409, -0.053), (-0.380, -0.044),
        (-0.352, -0.039), (-0.324, -0.037), (-0.290, -0.033), (Y_RECV_R, Z_BODY_B),
    ]
    # Fenêtre : le cadre garde 22 mm de matière partout (crosse squelette)
    void = [(-0.275, 0.0140), (-0.442, 0.0060), (-0.442, -0.0340), (-0.290, -0.0020)]
    stock = prism_x(stock_side, -0.0190, 0.0190)
    void3 = prism_x(void, -0.030, 0.030)
    b.add(mk.difference(stock, [void3]), MAT_BLACK, name="stock_frame")

    butt = prism_x([(-0.481, 0.024), (Y_BUTT, 0.024), (Y_BUTT, -0.127),
                    (-0.481, -0.127)], -0.0200, 0.0200)
    b.add(butt, MAT_RUBBER, name="butt_pad")

    # ================================================================== #
    # 6. POIGNÉE PISTOLET — 60 mm de large, bas à -141 mm
    # ================================================================== #
    g_top = np.array([0.0, -0.173, Z_BODY_B + 0.006])
    g_bot = np.array([0.0, -0.200, -0.141])
    axis = g_bot - g_top
    au = axis / np.linalg.norm(axis)
    rings = []
    for i in range(9):
        t = i / 8.0
        c = g_top + axis * t + np.array([0.0, 0.0045 * math.sin(math.pi * t), 0.0])
        rings.append(ring_ch(c, axis, 0.0168 - 0.0016 * t,
                             0.0232 - 0.0052 * t * t, 0.0030))
    rings.append(ring_ch(g_bot + au * 0.006, axis, 0.0150, 0.0172, 0.0028))
    b.add(mk.loft(rings, caps=True), MAT_BLACK, name="pistol_grip")

    # ================================================================== #
    # 7. PONTET + DÉTENTE (bas mesuré à -78 mm)
    # ================================================================== #
    guard_out = [(-0.098, Z_BODY_B), (-0.098, -0.052), (-0.110, -0.072),
                 (-0.135, -0.080), (-0.154, -0.076), (-0.168, -0.058),
                 (-0.168, Z_BODY_B)]
    guard_in = [(-0.106, -0.038), (-0.160, -0.038), (-0.160, -0.062),
                (-0.120, -0.068)]
    guard = prism_x(guard_out, -0.0055, 0.0055)
    b.add(mk.difference(guard, [prism_x(guard_in, -0.020, 0.020)]),
          MAT_BLACK, name="trigger_guard")
    b.add(prism_x([(-0.150, Z_BODY_B), (-0.142, Z_BODY_B), (-0.144, -0.050),
                   (-0.153, -0.054)], -0.0026, 0.0026), MAT_BRIGHT, name="trigger")

    # ================================================================== #
    # 8. CHARGEUR — 95 mm avant-arrière, bas à -194 mm
    # ================================================================== #
    mag_side = [
        (0.002, Z_BODY_B), (-0.078, Z_BODY_B), (-0.078, -0.110),
        (-0.070, -0.170), (-0.062, -0.194), (-0.002, -0.178), (0.001, -0.100),
    ]
    b.add(shell(mag_side, 0.0152, -0.100, 0.0900, 0.0022, -0.081, 0.006),
          MAT_MAG, name="magazine")
    well = prism_x([(0.010, Z_BODY_B), (-0.098, Z_BODY_B), (-0.096, -0.062),
                    (0.008, -0.062)], -0.0235, 0.0235)
    b.add(well, MAT_POLY, name="magwell")
    # trous témoins + nervures
    holes = []
    for k in range(5):
        zz = -0.062 - 0.0245 * k
        for sx in (-1, 1):
            h = mk.cylinder(0.0032, 0.0022, sections=14)
            mk.rot_y(h, 90.0)
            mk.place(h, sx * 0.0140, -0.026, zz)
            holes.append(h)
    b.add(mk.union(holes), MAT_BLACK, name="mag_witness_holes")
    ribs = []
    for k in range(4):
        zz = -0.060 - 0.032 * k
        rib = mk.box(0.0330, 0.0900, 0.0030)
        mk.place(rib, 0.0, -0.026, zz)
        ribs.append(rib)
    b.add(mk.intersection(mk.union(ribs),
                          prism_x(mag_side, -0.0168, 0.0168)), MAT_BLACK, name="mag_ribs")

    # ================================================================== #
    # 9. CANON — Ø20, cache-flammes Ø23, hausse repliée
    # ================================================================== #
    barrel = mk.cylinder(0.0100, 0.134, sections=26)
    mk.rot_x(barrel, -90.0)
    mk.place(barrel, 0.0, Y_HG_F, 0.0)
    b.add(barrel, MAT_STEEL, name="barrel")

    sight = prism_x([(0.296, 0.011), (0.296, 0.028), (0.310, 0.031), (0.318, 0.024)],
                    -0.0090, 0.0090)
    b.add(sight, MAT_STEEL, name="front_sight_folded")

    fh = mk.tube(0.0118, 0.0084, 0.054, sections=30)
    mk.rot_x(fh, -90.0)
    mk.place(fh, 0.0, Y_FH_R, 0.0)
    slots = []
    for k in range(6):
        c = mk.box(0.0028, 0.020, 0.030)
        mk.rot_x(c, -75.0 + 30.0 * k)
        mk.place(c, 0.0, Y_FH_R + 0.028, 0.0)
        slots.append(c)
    b.add(mk.difference(fh, slots), MAT_STEEL, name="flash_hider")

    # bague de grenadière sous le garde-main
    loop = mk.tube(0.0050, 0.0030, 0.0075, sections=20)
    mk.rot_y(loop, 90.0)
    mk.place(loop, -0.0038, 0.286, -0.036)
    b.add(loop, MAT_STEEL_DK, name="sling_loop_front")

    # ================================================================== #
    # 10. MÉCANIQUE
    # ================================================================== #
    b.add(prism_x([(0.068, Z_RC_T - 0.004), (0.068, Z_RC_T + 0.010),
                   (0.104, Z_RC_T + 0.013), (0.110, Z_RC_T - 0.002)],
                  -0.0075, 0.0075), MAT_STEEL_DK, name="charging_handle")
    port = mk.box(0.0050, 0.060, 0.024)
    mk.place(port, HW_RC - 0.0015, 0.010, -0.002)
    b.add(port, MAT_STEEL_DK, name="ejection_port")
    for side, tag in ((1, "right"), (-1, "left")):
        sel = mk.cylinder(0.0075, 0.0080, sections=20)
        mk.rot_y(sel, 90.0)
        mk.place(sel, side * HW_RC, -0.150, -0.010)
        b.add(sel, MAT_BLACK, name=f"selector_{tag}")
        lev = prism_x([(-0.152, -0.016), (-0.152, -0.008), (-0.176, -0.022),
                       (-0.174, -0.030)], side * HW_RC - 0.0030, side * HW_RC + 0.0030)
        b.add(lev, MAT_BLACK, name=f"selector_lever_{tag}")
    pins = []
    for yy in (-0.198, -0.104, 0.104):
        p = mk.cylinder(0.0036, 2 * HW_RC + 0.002, sections=14)
        mk.rot_y(p, 90.0)
        mk.place(p, -HW_RC - 0.001, yy, -0.004)
        pins.append(p)
    b.add(mk.union(pins), MAT_STEEL, name="receiver_pins")
    hinge = mk.cylinder(0.0052, 2 * 0.0190 + 0.004, sections=20)
    mk.rot_y(hinge, 90.0)
    mk.place(hinge, -0.0210, Y_RECV_R, 0.012)
    b.add(hinge, MAT_STEEL, name="stock_hinge")
    # plaque de couche : grenadière
    b.add(prism_x([(-0.492, -0.052), (-0.500, -0.040), (-0.500, -0.030),
                   (-0.492, -0.028)], -0.0035, 0.0035), MAT_STEEL_DK, name="sling_loop_rear")

    # ================================================================== #
    # 11. SOCKETS
    # ================================================================== #
    b.def_socket("SOCKET_muzzle", pos=(0.0, Y_MUZZLE, 0.0))
    b.def_socket("SOCKET_grip", pos=(0.0, -0.200, -0.105))
    b.def_socket("SOCKET_optic", pos=(0.0, -0.150, Z_OPTIC_T))
    b.def_socket("SOCKET_eject", pos=(HW_RC, 0.010, 0.006))
    b.def_socket("SOCKET_mag", pos=(0.0, -0.040, -0.170))
    b.def_socket("SOCKET_rail_top", pos=(0.0, -0.040, Z_ARCH_T))
    b.def_socket("SOCKET_rail_bottom", pos=(0.0, 0.240, -0.031))
    b.def_socket("SOCKET_stock", pos=(0.0, Y_RECV_R, 0.012))
    return b


def ground(b: mk.Builder) -> mk.Builder:
    """Pose l'arme au sol (bas du chargeur à z = 0)."""
    lo = min(float(p[0].bounds[0][2]) for p in b.parts)
    for mesh, _mat, _lbl in b._parts:
        mesh.apply_translation([0.0, 0.0, -lo])
    for sname in b._sockets:
        b._sockets[sname]["position"][2] -= lo
    return b


if __name__ == "__main__":
    bb = ground(build())
    bad = [(l, m.is_watertight) for m, _mt, l in bb.parts if not m.is_watertight]
    print(bb.stats())
    print("non étanches:", bad if bad else "aucune")
