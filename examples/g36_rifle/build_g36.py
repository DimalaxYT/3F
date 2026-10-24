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
# Polymère translucide vert pâle du chargeur réel (la photo le montre presque
# aussi clair que le fond, c'est ce qui trompait le masque de référence).
MAT_MAG = mk.Material("g36_mag_translucent", "#a9b8a3", metallic=0.0,
                      roughness=0.24, opacity=0.62, transmission=0.35)
MAT_GLASS = mk.mat.glass("#c8d8dc", opacity=0.20, roughness=0.03)
MAT_RED = mk.mat.emissive("#ff2010", 2.6)
MAT_MAG_R = mk.Material("g36_mag_rib", "#87957f", metallic=0.0, roughness=0.34)
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
#
# L = 998 mm · H = 278 mm · axe du canon à 29 % de la hauteur.
# Chaque valeur ci-dessous sort du contour mesuré (voir extract_contours.py),
# pas d'une estimation à l'œil : c'est ce qui a manqué aux passes précédentes.
# --------------------------------------------------------------------------- #
Y_MUZZLE = 0.499
Y_BRAKE_R = 0.434       # base du frein de bouche
Y_BARREL_R = 0.322      # entrée du canon dans le garde-main
Y_HG_F = 0.3360         # pointe avant du garde-main
Y_HG_R = 0.1150         # garde-main / pilier d'arche
Y_RECV_R = -0.2603      # boîtier arrière / charnière de crosse
Y_BUTT = -0.499

Z_HG_T = 0.0280         # dessus du corps de garde-main (sous son rail)
Z_HG_RAIL_T = 0.0368    # dessus du rail de garde-main (mesuré)
Z_RC_T = 0.0540         # dessus de l'arche (sous son rail)
Z_RAIL_T = 0.0610       # dessus du rail haut (mesuré, plat sur 280 mm)
Z_BODY_B = -0.0300      # dessous commun garde-main / boîtier

HW_HG = 0.0305          # demi-largeur garde-main (61 mm)
HW_RC = 0.0295          # demi-largeur boîtier (59 mm)
CH_HG = 0.0022          # chanfrein : au-delà il mord le dessus et crée une facette
CH_RC = 0.0022

# Fenêtres mesurées (y0, z0, y1, z1)
# La fenêtre d'arche n'est PAS un rectangle : son plancher remonte de +25 mm à
# l'avant (le pilier) à +34 mm (le toit du boîtier) vers l'arrière. Mesuré sur
# le masque de la photo, trou de 3 983 mm² : y -129..+76, z +26..+53.
WIN_ARCH_PTS = [
    (0.0760, 0.0255), (0.0600, 0.0250), (0.0400, 0.0345), (-0.1290, 0.0335),
    (-0.1290, 0.0530), (0.0400, 0.0542), (0.0600, 0.0505), (0.0760, 0.0485),
]
WIN_ARCH = (0.0760, 0.0255, -0.1290, 0.0530)
WIN_STOCK = (-0.3213, -0.0185, -0.4630, 0.0100)  # 142 x 28 mm


def rail(y0: float, y1: float, z_base: float, teeth: int = 20,
         width: float = 0.0212, height: float = 0.0090) -> trimesh.Trimesh:
    """Rail Picatinny cranté posé à `z_base`, de y0 (arrière) à y1 (avant)."""
    r = gr.picatinny_rail(length=abs(y1 - y0), width=width,
                          height=height, teeth=teeth)
    mk.place(r, 0.0, (y0 + y1) / 2.0, z_base)
    return r


def build() -> mk.Builder:
    """G36 — contours relevés sur la photo, rails et fenêtres mesurés."""
    b = mk.Builder("g36_rifle")

    # ================================================================== #
    # 1. CORPS — garde-main + pilier + arche + boîtier d'un seul tenant.
    #    Le dessus suit le contour mesuré MOINS la hauteur des rails, qui
    #    sont posés dessus : la silhouette finale tombe donc juste.
    # ================================================================== #
    body_top_bot = [
        # dessous, de l'arrière vers l'avant
        # le dessous du boîtier descend à -39 mm en arrière de y = -200 mm :
        # c'est le logement de la détente, mesuré sur la photo
        (Y_RECV_R, -0.0390), (-0.2000, -0.0390), (-0.2000, -0.0460),
        (-0.0300, -0.0460), (0.0000, -0.0335), (0.3050, Z_BODY_B),
        (0.3210, -0.0135),
    ]
    body_outline = [
        # dessus, de l'avant vers l'arrière
        (Y_HG_F, 0.0060), (0.3300, 0.0110), (0.3150, 0.0225), (0.3025, Z_HG_T), (Y_HG_R, Z_HG_T),
        # rampe relevée sur la photo (dessus A) : +36 à y = +105, +42 à +100,
        # +46 à +95, +52 à +90, +55 à +85, +56 à +80 — c'est une courbe, pas
        # la droite que donnaient les cotes précédentes (376 mm² d'écart).
        (0.1100, 0.0330), (0.1050, 0.0365), (0.1000, 0.0420),
        (0.0950, 0.0465), (0.0900, 0.0520), (0.0850, 0.0550),
        (0.0780, 0.0556), (0.0600, Z_RC_T),
        (-0.2227, Z_RC_T), (-0.2336, 0.0585), (-0.2540, 0.0545),
        (-0.2575, 0.0490), (Y_RECV_R, 0.0407),
    ] + body_top_bot
    # section chanfreinée couvrant TOUTE la hauteur du corps
    z_lo, z_hi = -0.0475, Z_RAIL_T   # marge sous le dessous arrière (-46)
    body = shell(body_outline, HW_HG, (z_lo + z_hi) / 2, (z_hi - z_lo) / 2,
                 CH_HG, Y_RECV_R, Y_HG_F)

    # ouïes du garde-main : 2 rangées traversantes (mesurées z -0.024..+0.014)
    vents, pockets = [], []
    # Les ouïes du G36 sont des LUMIÈRES OVALES bien visibles en 3/4, mais le
    # masque de la photo n'en voit qu'un petit trou : la paroi opposée du
    # garde-main remplit le reste. On creuse donc une poche latérale de 20 x 10
    # (visible en volume) doublée d'une lumière traversante aux dimensions
    # mesurées (visible en silhouette).
    for yy in (0.305, 0.285, 0.265, 0.204, 0.183, 0.162, 0.142):
        for sx in (-1.0, 1.0):
            pk = mk.box(0.0090, 0.0200, 0.0100)
            mk.place(pk, sx * HW_HG, yy, 0.0060)
            pockets.append(pk)
        h = mk.box(0.090, 0.0060, 0.0030)
        mk.place(h, 0.0, yy, 0.0075)
        vents.append(h)
    # rangée basse : une longue lumière + une petite, mesurées
    for yy, ly, lz in ((0.2465, 0.0210, 0.0110), (0.2310, 0.0070, 0.0070)):
        for sx in (-1.0, 1.0):
            pk = mk.box(0.0090, ly, lz)
            mk.place(pk, sx * HW_HG, yy, -0.0170)
            pockets.append(pk)
        h = mk.box(0.090, ly, lz)
        mk.place(h, 0.0, yy, -0.0170)
        vents.append(h)

    # fenêtre de poignée de transport : forme mesurée, traversante
    win = prism_x(WIN_ARCH_PTS, -0.045, 0.045)
    body = mk.difference(body, vents + pockets + [win])
    b.add(body, MAT_POLY, name="body")

    # Rails posés sur les dessus mesurés (la silhouette finale tombe juste).
    # Attention : un rail plein au-dessus d'une fenêtre la bouche visuellement.
    # Le rail du dessus est donc évidé au-dessus de la fenêtre d'arche — il se
    # réduit à un pont de 2,5 mm qui forme le toit.
    b.add(rail(0.112, 0.315, Z_HG_T, teeth=18, height=Z_HG_RAIL_T - Z_HG_T),
          MAT_POLY_DK, name="handguard_rail")
    top_rail = rail(-0.244, 0.090, Z_RC_T, teeth=30, height=Z_RAIL_T - Z_RC_T)
    # découpe du rail au-dessus de la fenêtre : on enlève TOUT ce qui est
    # sous +25,2 mm sur la plage de la fenêtre (les dents descendent à +25,
    # elles bouchaient le haut de la fenêtre)
    # les dents du rail descendent à +45,7 mm : sous le toit de la fenêtre
    # (+53,0), elles boucheraient le haut du jour. On les rogne sur la plage.
    rail_win = prism_x([(-0.1275, 0.0400), (-0.1275, 0.0536),
                        (0.0745, 0.0536), (0.0745, 0.0400)],
                       -0.060, 0.060)
    b.add(mk.difference(top_rail, [rail_win]), MAT_POLY_DK,
          name="receiver_rail")

    # ================================================================== #
    # 2. CROSSE — cadre mesuré, fenêtre 142 x 29 mm, talon ajouré
    # ================================================================== #
    stock_outline = [
        (Y_RECV_R, 0.0375), (-0.2759, 0.0350), (-0.2994, 0.0310),
        (-0.3307, 0.0280), (-0.3698, 0.0290), (-0.4012, 0.0310),
        (-0.4246, 0.0350), (-0.4325, 0.0210), (-0.4403, 0.0210),
        (-0.4481, 0.0230), (-0.4559, 0.0270), (-0.4716, 0.0350),
        (-0.4865, 0.0340), (-0.4865, -0.1130),
        (-0.4716, -0.1130),
        (-0.4559, -0.1040), (-0.4403, -0.0880), (-0.4246, -0.0720),
        (-0.4012, -0.0630), (-0.3777, -0.0550), (-0.3464, -0.0430),
        (-0.3229, -0.0370), (-0.2916, -0.0400), (Y_RECV_R, -0.0380),
    ]
    stock = prism_x(stock_outline, -0.0150, 0.0150)
    # lumière à coins chanfreinés : rectangle plein débordait de 5 mm en haut
    # et en bas sur toute sa longueur (905 mm² d'écart mesurés)
    swin = prism_x([(-0.4640, -0.0060), (-0.4580, -0.0125), (-0.3450, -0.0125),
                    (-0.3350, -0.0175), (-0.3220, -0.0115), (-0.3220, 0.0020),
                    (-0.3450, 0.0085), (-0.4580, 0.0085), (-0.4640, 0.0040)],
                   -0.040, 0.040)
    b.add(mk.difference(stock, [swin]), MAT_POLY, name="stock_frame")

    # ================================================================== #
    # 3. PLAQUE DE COUCHE — échelles triangulaires de la référence
    # ================================================================== #
    # le talon de la photo est un gros galbe : 148 mm de haut à -486, 65 mm
    # à -498. Une face plane à -499 laissait 319 mm² d'écart.
    butt = prism_x([(-0.4865, 0.0340), (-0.4900, 0.0310), (-0.4930, 0.0270),
                    (-0.4950, 0.0180), (-0.4970, 0.0080), (-0.4985, -0.0050),
                    (-0.4985, -0.0660), (-0.4970, -0.0790), (-0.4950, -0.0890),
                    (-0.4930, -0.0985), (-0.4900, -0.1055), (-0.4865, -0.1130)],
                   -0.0165, 0.0165)
    ladder = []
    for k in range(7):
        zc = 0.024 - 0.0190 * k
        t = mk.cylinder(0.0040, 0.030, sections=12)
        mk.rot_y(t, 90.0)
        mk.place(t, -0.0225, -0.4935, zc)
        ladder.append(t)
    b.add(mk.difference(butt, ladder), MAT_POLY, name="butt_pad")

    # ================================================================== #
    # 4. CHARGEUR — banane mesurée : -33 en haut, pointe à -197
    # ================================================================== #
    # prisme simple (pas de shell : la forme est concave et shell() la découpait
    # mal, le chargeur perdait 45 mm de hauteur)
    # Contour relevé sur le masque (25 mm de moins à l'avant que la version
    # précédente : le chargeur est nettement plus raide, et son talon descend
    # en biais vers l'arrière).
    # La fente claire entre le dessous du boîtier et le dessus du chargeur est
    # RÉELLE sur la photo (on voit le fond au travers) : ne pas la combler.
    mag_side = [
        (-0.043, -0.046), (-0.044, -0.090), (-0.036, -0.115), (-0.028, -0.150),
        (-0.017, -0.178),            # coin avant-bas
        (-0.083, -0.196),            # talon arrière du plancher
        (-0.100, -0.140), (-0.107, -0.113), (-0.112, -0.085),
        (-0.118, -0.055), (-0.118, -0.046),
    ]
    b.add(prism_x(mag_side, -0.0125, 0.0125), MAT_MAG, name="magazine")
    ribs = []
    for k in range(6):
        zz = -0.050 - 0.0240 * k
        rb = mk.box(0.0246, 0.112, 0.0018)
        mk.place(rb, 0.0, -0.077, zz)
        ribs.append(rb)
    b.add(mk.intersection(mk.union(ribs),
                          prism_x(mag_side, -0.0129, 0.0129)),
          MAT_MAG_R, name="mag_ribs")

    # ================================================================== #
    # 5. POIGNÉE PISTOLET — mesurée : y -213..-272, pointe à -153
    # ================================================================== #
    # Profil relevé toutes les 10 mm de hauteur : la poignée est un
    # parallélogramme incliné vers l'arrière, pas un trapèze.
    grip_outline = [
        (-0.182, Z_BODY_B),
        (-0.190, -0.060), (-0.202, -0.095), (-0.207, -0.105),
        (-0.212, -0.115), (-0.217, -0.125), (-0.221, -0.135),
        (-0.224, -0.145), (-0.230, -0.150), (-0.243, -0.150),
        (-0.255, -0.142), (-0.265, -0.132), (-0.273, -0.125),
        (-0.267, -0.115), (-0.261, -0.105), (-0.255, -0.095),
        (-0.248, -0.085), (-0.242, -0.075), (-0.236, -0.065),
        (-0.230, -0.052), (-0.226, Z_BODY_B),
    ]
    b.add(prism_x(grip_outline, -0.0165, 0.0165), MAT_BLACK, name="pistol_grip")

    # ================================================================== #
    # 6. PONTET AJOURÉ — boucle mesurée, bas à -89
    # ================================================================== #
    # Le montant arrière du pontet s'amincit vers le haut : la photo montre
    # une patte en triangle (18 mm à la base, 4 mm sous le boîtier).
    guard_out = [(-0.104, Z_BODY_B), (-0.106, -0.060), (-0.110, -0.087),
                 (-0.120, -0.089), (-0.150, -0.089), (-0.172, -0.089),
                 (-0.181, -0.080), (-0.183, -0.070), (-0.177, -0.056),
                 (-0.174, Z_BODY_B)]
    guard_in = [(-0.140, -0.052), (-0.170, -0.054), (-0.172, -0.076),
                (-0.142, -0.079)]
    guard = prism_x(guard_out, -0.0052, 0.0052)
    b.add(mk.difference(guard, [prism_x(guard_in, -0.020, 0.020)]),
          MAT_POLY, name="trigger_guard")
    b.add(prism_x([(-0.140, Z_BODY_B), (-0.124, Z_BODY_B), (-0.126, -0.108),
                   (-0.138, -0.105)], -0.0026, 0.0026), MAT_BRIGHT,
          name="trigger")

    # ================================================================== #
    # 7. CANON + FREIN DE BOUCHE — Ø 15 mm, frein à fentes
    # ================================================================== #
    barrel = mk.cylinder(0.0075, 0.120, sections=22)
    mk.rot_x(barrel, -90.0)
    mk.place(barrel, 0.0, Y_BARREL_R, 0.0)
    b.add(barrel, MAT_STEEL, name="barrel")
    collar = mk.cylinder(0.0098, 0.014, sections=22)
    mk.rot_x(collar, -90.0)
    mk.place(collar, 0.0, 0.4250, 0.0)
    b.add(collar, MAT_STEEL, name="barrel_collar")

    brake = mk.cylinder(0.0105, 0.064, sections=22)
    mk.rot_x(brake, -90.0)
    mk.place(brake, 0.0, Y_BRAKE_R, 0.0)
    slots = []
    for k in range(3):
        for sign in (-1, 1):
            sl = mk.box(0.018, 0.0060, 0.0125)
            mk.place(sl, sign * 0.0072, 0.446 + 0.0115 * k, 0.0)
            slots.append(sl)
    for updown in (1, -1):
        sl = mk.box(0.024, 0.0055, 0.0125)
        mk.place(sl, 0.0, 0.465, updown * 0.0072)
        slots.append(sl)
    bore = mk.cylinder(0.0038, 0.090, sections=16)
    mk.rot_x(bore, -90.0)
    mk.place(bore, 0.0, 0.430, 0.0)
    slots.append(bore)
    b.add(mk.difference(brake, slots), MAT_STEEL, name="muzzle_brake")

    # ================================================================== #
    # 8. MÉCANIQUE DE SURFACE
    # ================================================================== #
    # hausses repliées : mesurées à +80,6 (avant) et +75,1 (arrière)
    fsp = prism_x([(0.0640, Z_RAIL_T), (0.0640, 0.0806), (0.0690, 0.0806),
                   (0.0690, Z_RAIL_T)], -0.0035, 0.0035)
    b.add(fsp, MAT_STEEL, name="front_sight")
    rsp = prism_x([(-0.2360, Z_RAIL_T), (-0.2360, 0.0751), (-0.2310, 0.0751),
                   (-0.2310, Z_RAIL_T)], -0.0035, 0.0035)
    b.add(rsp, MAT_STEEL, name="rear_sight")

    # disque de charnière de crosse
    disc = mk.cylinder(0.0140, 0.0100, sections=26)
    mk.rot_y(disc, 90.0)
    mk.place(disc, -(HW_RC - 0.0010), Y_RECV_R + 0.016, -0.004)
    b.add(disc, MAT_POLY_DK, name="stock_hinge_disc")

    # sélecteur ambidextre
    for side, tag in ((1, "right"), (-1, "left")):
        s = mk.cylinder(0.0070, 0.0075, sections=20)
        mk.rot_y(s, 90.0)
        mk.place(s, side * (HW_RC - 0.0010), -0.152, -0.008)
        b.add(s, MAT_POLY_DK, name=f"selector_{tag}")
        lev = prism_x([(-0.154, -0.012), (-0.154, -0.004), (-0.180, -0.018),
                       (-0.178, -0.026)], side * HW_RC - 0.0030,
                      side * HW_RC + 0.0030)
        b.add(lev, MAT_BLACK, name=f"selector_lever_{tag}")

    # fenêtre d'éjection + déflecteur
    port = mk.box(0.0060, 0.056, 0.018)
    mk.place(port, HW_RC - 0.0018, 0.020, -0.008)
    b.add(port, MAT_STEEL_DK, name="ejection_port")
    b.add(prism_x([(-0.008, -0.010), (-0.008, 0.010), (-0.038, 0.016),
                   (-0.042, -0.006)], HW_RC - 0.0030, HW_RC + 0.0040),
          MAT_POLY, name="case_deflector")

    # poignée d'armement latérale
    b.add(prism_x([(0.048, 0.004), (0.048, 0.018), (0.086, 0.022),
                   (0.092, 0.002)], 0.0265, 0.0395), MAT_STEEL,
          name="charging_handle")

    # goupilles traversantes
    pins = []
    for yy in (-0.222, -0.104, 0.086):
        p = mk.cylinder(0.0032, 2 * HW_RC + 0.002, sections=14)
        mk.rot_y(p, 90.0)
        mk.place(p, -(HW_RC + 0.001), yy, -0.006)
        pins.append(p)
    b.add(mk.union(pins), MAT_STEEL, name="receiver_pins")

    # grenadière avant
    loop = mk.tube(0.0048, 0.0028, 0.0070, sections=20)
    mk.rot_y(loop, 90.0)
    mk.place(loop, -0.0036, 0.336, -0.014)
    b.add(loop, MAT_STEEL_DK, name="sling_loop_front")

    # ================================================================== #
    # 9. SOCKETS
    # ================================================================== #
    b.def_socket("SOCKET_muzzle", pos=(0.0, Y_MUZZLE, 0.0))
    b.def_socket("SOCKET_grip", pos=(0.0, -0.240, -0.110))
    b.def_socket("SOCKET_optic", pos=(0.0, -0.180, Z_RAIL_T))
    b.def_socket("SOCKET_eject", pos=(HW_RC, 0.020, -0.008))
    b.def_socket("SOCKET_mag", pos=(0.0, -0.055, -0.180))
    b.def_socket("SOCKET_rail_top", pos=(0.0, -0.060, Z_RAIL_T))
    b.def_socket("SOCKET_rail_bottom", pos=(0.0, 0.222, -0.030))
    b.def_socket("SOCKET_stock", pos=(0.0, Y_RECV_R, -0.004))
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
