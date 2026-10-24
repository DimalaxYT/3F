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
MAT_MAG_R = mk.Material("g36_mag_smoke", "#3a4448", metallic=0.0, roughness=0.22)
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
# Cotes maîtresses (m) — dépouillées au pixel sur la vue de profil
# L = 998 mm, H = 279 mm (L/H 3,574), axe du canon à 29 % de la hauteur.
# --------------------------------------------------------------------------- #
Y_MUZZLE = 0.499
Y_BRAKE_R = 0.446       # base du frein de bouche
Y_BARREL_R = 0.322      # entrée du canon dans le garde-main
Y_HG_F = 0.318          # pointe avant du garde-main
Y_HG_R = 0.143          # garde-main / boîtier
Y_RECV_R = -0.260       # boîtier arrière / charnière de crosse
Y_BUTT = -0.499

Z_HG_T = 0.036          # dessus du garde-main (base du rail)
Z_RC_T = 0.024          # dessus du boîtier, sous la fenêtre de poignée
Z_RAIL_T = 0.061        # dessus du rail haut
Z_BODY_B = -0.031       # dessous commun

HW_HG = 0.0305          # demi-largeur garde-main (61 mm)
HW_RC = 0.0295          # demi-largeur boîtier (59 mm)
CH_HG = 0.0080          # chanfreins larges : c'est ce qui fait lire la finesse
CH_RC = 0.0075


def rail(y0: float, y1: float, z_base: float, teeth: int = 20,
         width: float = 0.0210, height: float = 0.0125) -> trimesh.Trimesh:
    """Rail Picatinny cranté posé à `z_base`, de y0 (arrière) à y1 (avant)."""
    r = gr.picatinny_rail(length=abs(y1 - y0), width=width,
                          height=height, teeth=teeth)
    mk.place(r, 0.0, (y0 + y1) / 2.0, z_base)
    return r


def build() -> mk.Builder:
    """G36 — la référence est la version à rails intégrés, chargeur fumé."""
    b = mk.Builder("g36_rifle")

    # ================================================================== #
    # 1. GARDE-MAIN — nez biseauté puis bloc à dessus plat
    # ================================================================== #
    hg_side = [
        (0.322, -0.010), (0.312, 0.024), (0.300, Z_HG_T), (Y_HG_R, Z_HG_T),
        (Y_HG_R, Z_BODY_B), (0.300, Z_BODY_B), (0.318, -0.024),
    ]
    hg = shell(hg_side, HW_HG, (Z_HG_T + Z_BODY_B) / 2,
               (Z_HG_T - Z_BODY_B) / 2, CH_HG, Y_HG_R, Y_HG_F)

    # deux rangées d'ouïes traversantes, comme sur la référence
    vents = []
    for k in range(8):                       # rangée haute : petits trous ronds
        yy = 0.292 - 0.0180 * k
        for _sx in (-1, 1):
            v = mk.cylinder(0.0042, 0.075, sections=14)
            mk.rot_y(v, 90.0)
            mk.place(v, -(HW_HG + 0.010), yy, 0.0125)
            vents.append(v)
    for k in range(6):                       # rangée basse : lumières oblongues
        yy = 0.288 - 0.0235 * k
        for _sx in (-1, 1):
            v = mk.box(0.075, 0.0165, 0.0085)
            mk.place(v, -(HW_HG + 0.010), yy, -0.0055)
            vents.append(v)
    b.add(mk.difference(hg, vents), MAT_POLY, name="handguard")
    b.add(rail(0.150, 0.298, Z_HG_T, teeth=19), MAT_POLY_DK, name="handguard_rail")
    side_rail = gr.picatinny_rail(length=0.130, width=0.0165, height=0.0090, teeth=9)
    mk.rot_y(side_rail, -90.0)
    mk.place(side_rail, -(HW_HG + 0.0045), 0.222, -0.0180)
    b.add(side_rail, MAT_POLY_DK, name="handguard_rail_side")

    # ================================================================== #
    # 2. BOÎTIER
    # ================================================================== #
    rc_side = [
        (Y_HG_R, Z_RC_T), (Y_HG_R, Z_BODY_B), (-0.232, Z_BODY_B),
        (Y_RECV_R, -0.020), (Y_RECV_R, Z_RC_T),
    ]
    b.add(shell(rc_side, HW_RC, (Z_RC_T + Z_BODY_B) / 2,
                (Z_RC_T - Z_BODY_B) / 2, CH_RC, Y_RECV_R, Y_HG_R),
          MAT_POLY, name="receiver")

    # ================================================================== #
    # 3. POIGNÉE DE TRANSPORT : pilier avant + poutre + bloc arrière
    #    fenêtre mesurée 208 × 32 mm (y +79 → -129, z +24 → +56)
    # ================================================================== #
    bridge = prism_x([(0.104, Z_RC_T), (0.104, Z_RAIL_T), (-0.247, Z_RAIL_T),
                      (-0.260, 0.053), (-0.260, Z_RC_T)], -0.0135, 0.0135)
    window = prism_x([(0.079, Z_RC_T - 0.004), (0.079, 0.0560),
                      (-0.129, 0.0560), (-0.129, Z_RC_T - 0.004)],
                     -0.040, 0.040)
    b.add(mk.difference(bridge, [window]), MAT_POLY, name="carry_handle")
    b.add(rail(-0.244, 0.100, Z_RAIL_T, teeth=22), MAT_POLY_DK, name="receiver_rail")

    # hausse avant repliée sur le rail
    post = mk.box(0.0075, 0.0075, 0.0210)
    mk.place(post, 0.0, 0.056, Z_RAIL_T + 0.0125)
    b.add(post, MAT_STEEL, name="front_sight_post")

    # ================================================================== #
    # 4. BLOC ARRIÈRE (logement de la culasse) + œilleton
    # ================================================================== #
    b.add(prism_x([(-0.244, Z_RAIL_T), (-0.244, 0.052), (-0.262, 0.040),
                   (-0.262, Z_RAIL_T)], -0.0120, 0.0120),
          MAT_POLY, name="rear_sight_block")

    # ================================================================== #
    # 5. CROSSE — cadre, fenêtre mesurée 144 × 29 mm, talon à -113
    # ================================================================== #
    stock_side = [
        (Y_RECV_R, 0.028), (-0.290, 0.024), (-0.362, 0.024), (-0.430, 0.026),
        (-0.470, 0.028), (-0.492, 0.022), (Y_BUTT, -0.012),
        (Y_BUTT, -0.055), (-0.495, -0.084), (-0.489, -0.109), (-0.478, -0.113),
        (-0.463, -0.109), (-0.423, -0.070), (-0.343, -0.040), (-0.310, -0.035),
        (-0.272, -0.035), (Y_RECV_R, Z_BODY_B),
    ]
    stock = prism_x(stock_side, -0.0150, 0.0150)
    win = prism_x([(-0.321, 0.0120), (-0.465, 0.0120), (-0.465, -0.0170),
                   (-0.321, -0.0170)], -0.040, 0.040)
    b.add(mk.difference(stock, [win]), MAT_POLY, name="stock_frame")

    # talon : plaque ajourée d'échelles triangulaires (détail de la référence)
    butt = prism_x([(-0.484, 0.034), (Y_BUTT, 0.006), (Y_BUTT, -0.058),
                    (-0.484, -0.108)], -0.0165, 0.0165)
    ladder = []
    for k in range(6):
        zc = 0.018 - 0.0235 * k
        t = mk.cylinder(0.0068, 0.012, sections=3)
        mk.rot_y(t, 90.0)
        mk.place(t, -0.0175, -0.4975, zc)
        ladder.append(t)
    b.add(mk.difference(butt, ladder), MAT_POLY, name="butt_pad")

    # ================================================================== #
    # 6. POIGNÉE PISTOLET — inclinée, bas à -150
    # ================================================================== #
    g_top = np.array([0.0, -0.204, Z_BODY_B + 0.004])
    g_bot = np.array([0.0, -0.262, -0.150])
    axis = g_bot - g_top
    au = axis / np.linalg.norm(axis)
    rings = []
    for i in range(9):
        t = i / 8.0
        c = g_top + axis * t + np.array([0.0, 0.0050 * math.sin(math.pi * t), 0.0])
        rings.append(ring_ch(c, axis, 0.0150 - 0.0012 * t,
                             0.0225 - 0.0040 * t * t, 0.0035))
    rings.append(ring_ch(g_bot + au * 0.006, axis, 0.0138, 0.0165, 0.0032))
    b.add(mk.loft(rings, caps=True), MAT_BLACK, name="pistol_grip")

    # ================================================================== #
    # 7. PONTET AJOURÉ + DÉTENTE
    # ================================================================== #
    guard_out = [(-0.098, Z_BODY_B), (-0.098, -0.050), (-0.110, -0.070),
                 (-0.135, -0.078), (-0.158, -0.074), (-0.172, -0.056),
                 (-0.172, Z_BODY_B)]
    guard_in = [(-0.107, -0.036), (-0.164, -0.036), (-0.164, -0.060),
                (-0.120, -0.066)]
    g = prism_x(guard_out, -0.0050, 0.0050)
    b.add(mk.difference(g, [prism_x(guard_in, -0.020, 0.020)]),
          MAT_POLY, name="trigger_guard")
    b.add(prism_x([(-0.152, Z_BODY_B), (-0.144, Z_BODY_B), (-0.146, -0.048),
                   (-0.155, -0.052)], -0.0026, 0.0026), MAT_BRIGHT, name="trigger")

    # ================================================================== #
    # 8. CHARGEUR — bas à -197, cintré vers l'arrière
    # ================================================================== #
    mag_side = [
        (-0.021, Z_BODY_B), (-0.105, Z_BODY_B), (-0.104, -0.090),
        (-0.098, -0.150), (-0.092, -0.197), (-0.048, -0.197),
        (-0.042, -0.140), (-0.030, -0.080),
    ]
    b.add(prism_x(mag_side, -0.0126, 0.0126), MAT_MAG, name="magazine")
    # nervures transversales du chargeur fumé
    ribs = []
    for k in range(6):
        zz = -0.052 - 0.0230 * k
        rb = mk.box(0.0270, 0.070, 0.0022)
        mk.place(rb, 0.0, -0.062, zz)
        ribs.append(rb)
    b.add(mk.intersection(mk.union(ribs),
                          prism_x(mag_side, -0.0129, 0.0129)),
          MAT_MAG_R, name="mag_ribs")
    well = prism_x([(0.036, Z_BODY_B), (-0.096, Z_BODY_B), (-0.096, -0.058),
                    (0.036, -0.058)], -0.0205, 0.0205)
    b.add(well, MAT_POLY, name="magwell")

    # ================================================================== #
    # 9. CANON + FREIN DE BOUCHE
    # ================================================================== #
    barrel = mk.cylinder(0.0086, 0.132, sections=24)
    mk.rot_x(barrel, -90.0)
    mk.place(barrel, 0.0, Y_BARREL_R, 0.0)
    b.add(barrel, MAT_STEEL, name="barrel")
    collar = mk.cylinder(0.0112, 0.012, sections=24)
    mk.rot_x(collar, -90.0)
    mk.place(collar, 0.0, 0.430, 0.0)
    b.add(collar, MAT_STEEL, name="barrel_collar")

    brake = mk.cylinder(0.0112, 0.050, sections=24)
    mk.rot_x(brake, -90.0)
    mk.place(brake, 0.0, Y_BRAKE_R, 0.0)
    slots = []
    for k in range(3):                       # 3 paires de fentes latérales
        for sign in (-1, 1):
            sl = mk.box(0.020, 0.0068, 0.0130)
            mk.place(sl, sign * 0.0080, 0.458 + 0.0135 * k, 0.0)
            slots.append(sl)
    for updown in (1, -1):                   # 2 fentes sur le dessus/dessous
        sl = mk.box(0.028, 0.0060, 0.0130)
        mk.place(sl, 0.0, 0.472, updown * 0.0080)
        slots.append(sl)
    bore = mk.cylinder(0.0040, 0.075, sections=18)
    mk.rot_x(bore, -90.0)
    mk.place(bore, 0.0, 0.438, 0.0)
    slots.append(bore)
    b.add(mk.difference(brake, slots), MAT_STEEL, name="muzzle_brake")

    # ================================================================== #
    # 10. MÉCANIQUE DE SURFACE
    # ================================================================== #
    # disque de charnière de crosse (le gros bouton rond de la référence)
    disc = mk.cylinder(0.0145, 0.0100, sections=26)
    mk.rot_y(disc, 90.0)
    mk.place(disc, -(HW_RC - 0.0010), Y_RECV_R + 0.014, -0.006)
    b.add(disc, MAT_POLY_DK, name="stock_hinge_disc")

    # sélecteur : levier + disque
    for side, tag in ((1, "right"), (-1, "left")):
        s = mk.cylinder(0.0072, 0.0075, sections=20)
        mk.rot_y(s, 90.0)
        mk.place(s, side * (HW_RC - 0.0010), -0.150, -0.010)
        b.add(s, MAT_POLY_DK, name=f"selector_{tag}")
        lev = prism_x([(-0.152, -0.014), (-0.152, -0.006), (-0.178, -0.020),
                       (-0.176, -0.028)], side * HW_RC - 0.0030, side * HW_RC + 0.0030)
        b.add(lev, MAT_BLACK, name=f"selector_lever_{tag}")

    # fenêtre d'éjection + déflecteur
    port = mk.box(0.0060, 0.058, 0.020)
    mk.place(port, HW_RC - 0.0018, 0.020, -0.006)
    b.add(port, MAT_STEEL_DK, name="ejection_port")
    b.add(prism_x([(-0.010, -0.006), (-0.010, 0.014), (-0.040, 0.020),
                   (-0.044, -0.002)], HW_RC - 0.0030, HW_RC + 0.0040),
          MAT_POLY, name="case_deflector")

    # poignée d'armement latérale
    b.add(prism_x([(0.052, 0.006), (0.052, 0.020), (0.090, 0.024), (0.096, 0.004)],
                  0.0270, 0.0400), MAT_STEEL, name="charging_handle")

    # goupilles traversantes
    pins = []
    for yy in (-0.222, -0.104, 0.086):
        p = mk.cylinder(0.0034, 2 * HW_RC + 0.002, sections=14)
        mk.rot_y(p, 90.0)
        mk.place(p, -(HW_RC + 0.001), yy, -0.004)
        pins.append(p)
    b.add(mk.union(pins), MAT_STEEL, name="receiver_pins")

    # grenadière avant sous le garde-main
    loop = mk.tube(0.0050, 0.0030, 0.0075, sections=20)
    mk.rot_y(loop, 90.0)
    mk.place(loop, -0.0038, 0.286, -0.036)
    b.add(loop, MAT_STEEL_DK, name="sling_loop_front")

    # ================================================================== #
    # 11. SOCKETS
    # ================================================================== #
    b.def_socket("SOCKET_muzzle", pos=(0.0, Y_MUZZLE, 0.0))
    b.def_socket("SOCKET_grip", pos=(0.0, -0.240, -0.110))
    b.def_socket("SOCKET_optic", pos=(0.0, -0.180, Z_RAIL_T))
    b.def_socket("SOCKET_eject", pos=(HW_RC, 0.020, -0.006))
    b.def_socket("SOCKET_mag", pos=(0.0, -0.030, -0.180))
    b.def_socket("SOCKET_rail_top", pos=(0.0, -0.060, Z_RAIL_T + 0.0125))
    b.def_socket("SOCKET_rail_bottom", pos=(0.0, 0.222, -0.026))
    b.def_socket("SOCKET_stock", pos=(0.0, Y_RECV_R, -0.006))
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
