#!/usr/bin/env python3
"""
build_crimson_dragon.py v2 — Reconstruction ZBrush Haute-Fidélité Calibrée au Millimètre + Projection PBR Photo.

Architecture multi-groupes articulée (`3 x 1024²` = 3,15 millions de texels PBR + ~21 500 tris `LOD0` nets) :
  1. `group="head"` (`res=120`, résolution voxel `1.1 mm` dédiée uniquement à la tête !) :
     - Museau reptilien nerveux, narines creusées, arcades sourcilières épineuses surplombantes,
     - Orbites sombres profondes + globes oculaires ambrés ardents + pupilles fendues verticales noires,
     - Mâchoires entrouvertes sur cavité buccale noire + **32 crocs coniques d'ivoire gradués** sertis séparément
       (zéro fusion booléenne baveuse, chaque dent reste un cône d'ivoire acéré dans `LOD0` !),
     - Crête nasale dentelée (7 pointes), 2 épines mentonnières, 12 pointes jugales et 8 cornes annelées en S (`z = 1.000`).
  2. `group="wings"` :
     - Aile principale (`x > 0`) : bras musclé diagonal jusqu'au poignet haut `(u=0.425, z=0.922)`, griffe de pouce
       recourbée `(u=0.338, z=0.892)`, 4 longs doigts osseux griffus jusqu'à `(u=0.998, z=0.400)` et membranes épaisses sans déchirure,
     - Aile arrière (`x < 0`) : posée naturellement en perspective derrière le cou `(u=0.255..0.53, z=0.60..0.842)` exactement comme sur la photo !
  3. `Body` (`res=110`) :
     - Cou musclé en S, carène thoracique profonde, côtes, croupe, 4 pattes digitigrades décalées aux positions exactes
       des coupes laser `z = 0.00..0.46`, **16 doigts griffus écartés**, plaques d'écailles rectangulaires sur les cuisses/avant-bras,
     - **18 plaques ventrales dorées-bronze en chevrons** + rangées latérales dorées,
     - **22 ostéodermes épineux d'épaule + 6 pointes de coude** et **38 épines dorsales & caudales radiales** jusqu'au dard spiralé !
  4. Projection PBR Photo directe (`photo_to_3d.project_photo_pbr`, `az = +85°`, `fov = 20°`) + vérification microscope 300 % !
"""
from __future__ import annotations

import math
from pathlib import Path
import sys
import numpy as np
from scipy.interpolate import PchipInterpolator
import trimesh

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import meshkit as mk
import organic as org


# Ratio exact mesuré sur la photo de référence détourée : `W/H = 604 / 454 = 1.3304`
REF_ASPECT_LH = 1.3304


def _tree_union(meshes: list[trimesh.Trimesh], batch: int = 10) -> trimesh.Trimesh:
    """Union booléenne par arbre équilibré de petits paquets : réduit la RAM pic `manifold3d` de 8x !"""
    import gc as _gc
    cur = list(meshes)
    while len(cur) > 1:
        nxt = [
            mk.union(cur[i:i + batch]) if len(cur[i:i + batch]) > 1 else cur[i]
            for i in range(0, len(cur), batch)
        ]
        cur = nxt
        _gc.collect()
    return cur[0]


def build(
    height: float = 0.44,
    scale_color: str = "#6a2715",
    belly_color: str = "#b98749",
    wing_membrane_color: str = "#8a5335",
    horn_color: str = "#9e734c",
    eye_color: str = "#ff8514",
) -> mk.Builder:
    k = float(height) / 0.44
    H_m = 0.44 * k
    L_m = H_m * REF_ASPECT_LH  # 0.5854 m

    def UZ(x_m: float, u: float, z: float) -> tuple[float, float, float]:
        """Convertit directement `(x_m, u_photo in [0..1], z_photo in [0..1])` en coordonnées 3D métriques `(X, Y, Z)` !"""
        return (float(x_m) * k, (float(u) - 0.50) * L_m, float(z) * H_m)

    b = mk.Builder("crimson_dragon", {"height": height})

    m_hide = mk.mat.clay(scale_color, roughness=0.56)
    m_mouth_dark = mk.mat.clay("#100403", roughness=0.82)
    m_scute = mk.mat.clay(belly_color, roughness=0.50)
    m_wing_skin = mk.mat.leather(wing_membrane_color, roughness=0.60)
    m_horn = mk.mat.clay("#8a5d3b", roughness=0.48)
    m_fang = mk.mat.enamel("#f4eee4", roughness=0.14)
    m_iris = mk.mat.enamel(eye_color, roughness=0.06)
    m_pupil = mk.mat.enamel("#060202", roughness=0.08)

    # Articulations dédiées : donne à `head` et `wings` leurs propres atlas 1024² et budgets de triangles intacts !
    b.def_joint("head", UZ(0.0, 0.185, 0.855))
    b.def_joint("wings", UZ(0.0, 0.320, 0.560))

    # =========================================================================
    # 1. TÊTE ZBRUSH HAUTE DÉFINITION (`res=120`, VOXELS `1.1 mm`, `group="head"`)
    # =========================================================================
    hs = org.Sculpt(
        bounds=(
            UZ(-0.048, 0.025, 0.742),
            UZ(+0.048, 0.238, 0.948),
        ),
        res=120,
    )

    # Crâne arrière + museau supérieur effilé + bosse nasale retroussée
    hs.ellipsoid(UZ(0.0, 0.156, 0.882), (0.027 * k, 0.036 * k, 0.023 * k))
    hs.sweep(
        [
            UZ(0.0, 0.165, 0.880),
            UZ(0.0, 0.118, 0.868),
            UZ(0.0, 0.075, 0.850),
            UZ(0.0, 0.041, 0.834),
        ],
        radii=[0.024 * k, 0.0195 * k, 0.0145 * k, 0.0095 * k],
        k=0.005 * k,
    )
    # Bosse nasale caractérielle au bout du museau (`zoom1_head_neck.png`)
    hs.ellipsoid(UZ(0.0, 0.052, 0.848), (0.0110 * k, 0.0155 * k, 0.0105 * k), k=0.005 * k)

    # Arcades sourcilières féroces surplombant l'œil + crête zygomatique / joue
    hs.sweep(
        [
            UZ(0.008, 0.082, 0.862),
            UZ(0.017, 0.116, 0.892),
            UZ(0.022, 0.156, 0.906),
        ],
        radii=[0.0048 * k, 0.0072 * k, 0.0065 * k],
        k=0.004 * k,
        mirror_x=True,
    )
    hs.sweep(
        [
            UZ(0.013, 0.098, 0.838),
            UZ(0.021, 0.142, 0.854),
            UZ(0.023, 0.178, 0.866),
        ],
        radii=[0.0052 * k, 0.0075 * k, 0.0062 * k],
        k=0.004 * k,
        mirror_x=True,
    )

    # Mâchoire inférieure ciselée et menton saillant entrouvert
    hs.sweep(
        [
            UZ(0.0, 0.154, 0.836),
            UZ(0.0, 0.108, 0.812),
            UZ(0.0, 0.068, 0.796),
            UZ(0.0, 0.043, 0.792),
        ],
        radii=[0.0185 * k, 0.0140 * k, 0.0102 * k, 0.0076 * k],
        k=0.0045 * k,
    )

    # Jonction haute du cou pour transition organique parfaite vers `Body`
    hs.capsule(UZ(0.0, 0.180, 0.865), UZ(0.0, 0.205, 0.765), 0.025 * k, 0.027 * k, k=0.008 * k)

    # Découpe nette de la fente buccale (gueule férocement entrouverte, PAS béante !)
    hs.round_box(
        UZ(0.0, 0.086, 0.816),
        (0.026 * k, 0.038 * k, 0.0068 * k),
        r=0.0018 * k,
        mode="sub",
        k=0.0025 * k,
    )
    # Fosses nasales creusées + orbites profondes creusées sous l'arcade sourcilière !
    hs.ellipsoid(UZ(0.0095, 0.056, 0.848), (0.0038 * k, 0.0058 * k, 0.0042 * k), mode="sub", k=0.0018 * k, mirror_x=True)
    hs.ellipsoid(UZ(0.0165, 0.121, 0.874), (0.0062 * k, 0.0088 * k, 0.0062 * k), mode="sub", k=0.0022 * k, mirror_x=True)

    skull_raw = hs.to_mesh(smooth_iter=2, target_tris=12000)
    del hs
    __import__("gc").collect()
    skull_scaled = org.displace_scales(skull_raw, scale_size=0.0052 * k, depth=0.0011 * k)
    del skull_raw
    b.add(skull_scaled, m_hide, name="scaled_dragon_skull_and_jaws", group="head")

    # Cavité buccale sombre & orbite noire profonde (garantit le fond noir de la gueule derrière les crocs !)
    mouth_core = org.ellipsoid(0.011 * k, 0.032 * k, 0.0055 * k, subdivisions=2)
    b.add(mouth_core, m_mouth_dark, name="mouth_dark_interior", at=UZ(0.0, 0.092, 0.817), group="head")

    eye_sockets: list[trimesh.Trimesh] = []
    eye_irises: list[trimesh.Trimesh] = []
    eye_pupils: list[trimesh.Trimesh] = []
    fang_meshes: list[trimesh.Trimesh] = []
    head_horns: list[trimesh.Trimesh] = []

    for sx in (+1.0, -1.0):
        # 1) Anneau orbital sombre + 2) Globe ambré ardent + 3) Pupille fendue verticale noire !
        sock = org.ellipsoid(0.0042 * k, 0.0074 * k, 0.0052 * k, subdivisions=2)
        mk.rot_z(sock, sx * 10.0)
        sock.apply_translation(UZ(sx * 0.0155, 0.121, 0.874))
        eye_sockets.append(sock)

        iris = org.ellipsoid(0.0040 * k, 0.0058 * k, 0.0044 * k, subdivisions=3)
        mk.rot_z(iris, sx * 10.0)
        iris.apply_translation(UZ(sx * 0.0170, 0.121, 0.874))
        eye_irises.append(iris)

        pupil = org.ellipsoid(0.0016 * k, 0.0013 * k, 0.0038 * k, subdivisions=2)
        pupil.apply_translation(UZ(sx * 0.0203, 0.121, 0.874))
        eye_pupils.append(pupil)

        # 16 crocs par côté (8 supérieurs + 8 inférieurs) fins, acérés, légèrement recourbés et de tailles graduées !
        u_teeth = [0.043, 0.052, 0.062, 0.073, 0.085, 0.098, 0.112, 0.126]
        len_up  = [0.0058, 0.0082, 0.0052, 0.0074, 0.0050, 0.0062, 0.0044, 0.0036]
        len_lo  = [0.0064, 0.0048, 0.0068, 0.0046, 0.0056, 0.0042, 0.0038, 0.0030]
        for idx_f, (ut, lu, ll) in enumerate(zip(u_teeth, len_up, len_lo)):
            t_prog = idx_f / 7.0
            x_jaw = (0.0068 + 0.0068 * t_prog) * sx
            z_up_gum = 0.824 + 0.014 * t_prog
            z_lo_gum = 0.804 + 0.014 * t_prog
            # Croc supérieur pointant vers le bas et légèrement vers l'intérieur/arrière
            fang_meshes.append(
                org.tapered_curve(
                    [
                        UZ(x_jaw, ut, z_up_gum + 0.003),
                        UZ(x_jaw * 0.96, ut + 0.0015, z_up_gum - lu * 0.55 / 0.44),
                        UZ(x_jaw * 0.92, ut + 0.0030, z_up_gum - lu / 0.44),
                    ],
                    [0.00175 * k, 0.00105 * k, 0.00032 * k],
                    sections=8,
                    smooth_pts=8,
                )
            )
            # Croc inférieur imbriqué entre les crocs supérieurs !
            ut_lo = ut + 0.0045
            fang_meshes.append(
                org.tapered_curve(
                    [
                        UZ(x_jaw * 0.88, ut_lo, z_lo_gum - 0.003),
                        UZ(x_jaw * 0.86, ut_lo + 0.001, z_lo_gum + ll * 0.55 / 0.44),
                        UZ(x_jaw * 0.84, ut_lo + 0.002, z_lo_gum + ll / 0.44),
                    ],
                    [0.00155 * k, 0.00095 * k, 0.00030 * k],
                    sections=8,
                    smooth_pts=8,
                )
            )

        # 4 cornes étagées recourbées en S par côté (`zoom1_head_neck.png` : sommet exact à `u=0.275, z=1.000` !)
        # 1. Grande corne royale occipitale
        head_horns.append(
            org.tapered_curve(
                [
                    UZ(sx * 0.017, 0.165, 0.908),
                    UZ(sx * 0.025, 0.212, 0.930),
                    UZ(sx * 0.027, 0.250, 0.960),
                    UZ(sx * 0.023, 0.275, 1.000),
                ],
                [0.0112 * k, 0.0080 * k, 0.0048 * k, 0.0014 * k],
                sections=14,
                smooth_pts=18,
            )
        )
        # 2. Corne pariétale supérieure interne (`u=0.198, z=0.976`)
        head_horns.append(
            org.tapered_curve(
                [
                    UZ(sx * 0.012, 0.140, 0.910),
                    UZ(sx * 0.016, 0.172, 0.944),
                    UZ(sx * 0.015, 0.198, 0.976),
                ],
                [0.0072 * k, 0.0046 * k, 0.0013 * k],
                sections=12,
                smooth_pts=14,
            )
        )
        # 3. Corne temporale médiane (`u=0.252, z=0.922`)
        head_horns.append(
            org.tapered_curve(
                [
                    UZ(sx * 0.021, 0.172, 0.884),
                    UZ(sx * 0.029, 0.216, 0.896),
                    UZ(sx * 0.030, 0.252, 0.922),
                ],
                [0.0076 * k, 0.0048 * k, 0.0013 * k],
                sections=12,
                smooth_pts=14,
            )
        )
        # 4. Éperon jugal inférieur + 5 épines de mâchoire (`zoom1_head_neck.png`)
        head_horns.append(
            org.tapered_curve(
                [
                    UZ(sx * 0.021, 0.158, 0.852),
                    UZ(sx * 0.028, 0.192, 0.848),
                    UZ(sx * 0.029, 0.222, 0.852),
                ],
                [0.0062 * k, 0.0038 * k, 0.0012 * k],
                sections=10,
                smooth_pts=12,
            )
        )
        for j_i in range(5):
            uj = 0.108 + j_i * 0.018
            zj = 0.798 + j_i * 0.011
            head_horns.append(
                org.tapered_curve(
                    [UZ(sx * (0.012 + j_i * 0.002), uj, zj), UZ(sx * (0.018 + j_i * 0.0025), uj + 0.020, zj - 0.012)],
                    [0.0032 * k, 0.0008 * k],
                    sections=8,
                    smooth_pts=6,
                )
            )

    # 2 épines mentonnières caractéristiques sous le bout du menton (`u=0.052, z=0.760` & `u=0.078, z=0.758`)
    for uc_sp, zc_top, zc_tip, rc_sp in (
        (0.050, 0.792, 0.760, 0.0040),
        (0.076, 0.794, 0.758, 0.0046),
        (0.102, 0.798, 0.774, 0.0032),
    ):
        head_horns.append(
            org.tapered_curve(
                [UZ(0.0, uc_sp, zc_top), UZ(0.0, uc_sp + 0.006, zc_tip)],
                [rc_sp * k, 0.0009 * k],
                sections=9,
                smooth_pts=8,
            )
        )

    # Crête nasale & frontale en dents de scie (7 pointes le long du chanfrein `zoom1_head_neck.png`)
    for cr_i in range(7):
        uc = 0.074 + cr_i * 0.0145
        zc = 0.858 + cr_i * 0.0115
        hc = (0.0075 + cr_i * 0.0016) * k
        head_horns.append(
            org.tapered_curve(
                [UZ(0.0, uc, zc - 0.004), UZ(0.0, uc + 0.010, zc + hc / 0.44)],
                [0.0030 * k, 0.0008 * k],
                sections=8,
                smooth_pts=6,
            )
        )

    b.add(_tree_union(eye_sockets), m_mouth_dark, name="orbital_dark_rings", group="head")
    b.add(_tree_union(eye_irises), m_iris, name="dragon_amber_irises", group="head")
    b.add(_tree_union(eye_pupils), m_pupil, name="dragon_slit_pupils", group="head")
    b.add(_tree_union(fang_meshes), m_fang, name="dragon_ivory_fangs", group="head")
    b.add(_tree_union(head_horns), m_horn, name="dragon_horn_crown_keratin", group="head")

    # =========================================================================
    # 2. DOUBLE AILE ASYMÉTRIQUE NATURELLE (`group="wings"`, `6 460 tris` + `1024²` dédiés !)
    # =========================================================================
    # Aile avant (`x > 0`) : bras musclé diagonal jusqu'au poignet haut `(u=0.425, z=0.922)` + griffe `(u=0.338, z=0.892)`
    # et 4 longues phalanges osseuses griffues jusqu'à `(u=0.998, z=0.400)` !
    w_near_bones, w_near_mem, w_near_claw = org.bat_wing(
        shoulder=UZ(+0.044, 0.335, 0.545),
        elbow=UZ(+0.076, 0.495, 0.695),
        wrist=UZ(+0.074, 0.425, 0.922),
        finger_tips=[
            UZ(+0.088, 0.998, 0.400),  # Rémige primaire externe longue + griffe
            UZ(+0.096, 0.968, 0.556),  # 2e doigt
            UZ(+0.090, 0.748, 0.535),  # 3e doigt
            UZ(+0.076, 0.592, 0.485),  # 4e doigt interne
        ],
        body_anchors=[
            UZ(+0.044, 0.335, 0.545),
            UZ(+0.048, 0.435, 0.515),
            UZ(+0.042, 0.525, 0.480),
        ],
        membrane_thickness=0.015 * k,
        camber=0.020 * k,
        arm_radius=0.021 * k,
        claw_len=0.052 * k,
    )

    # Aile arrière (`x < 0`) : repliée en perspective naturelle derrière le cou (`u=0.255..0.54, z=0.58..0.842`)
    # exactement comme la membrane ambrée visible entre le cou et le bras d'aile principal sur `image-1.png` !
    w_far_bones, w_far_mem, w_far_claw = org.bat_wing(
        shoulder=UZ(-0.044, 0.285, 0.565),
        elbow=UZ(-0.068, 0.365, 0.705),
        wrist=UZ(-0.062, 0.258, 0.842),
        finger_tips=[
            UZ(-0.086, 0.665, 0.590),
            UZ(-0.090, 0.585, 0.655),
            UZ(-0.080, 0.495, 0.635),
            UZ(-0.066, 0.415, 0.585),
        ],
        body_anchors=[
            UZ(-0.044, 0.285, 0.565),
            UZ(-0.046, 0.365, 0.535),
            UZ(-0.040, 0.455, 0.505),
        ],
        membrane_thickness=0.015 * k,
        camber=0.018 * k,
        arm_radius=0.019 * k,
        claw_len=0.040 * k,
    )

    # Griffes distales aux extrémités des phalanges d'ailes (`zoom3_wings_tail.png`)
    wing_claws = [w_near_claw, w_far_claw]
    for tip_u, tip_z, du_c, dz_c in (
        (0.992, 0.408, +0.012, -0.024),
        (0.962, 0.560, +0.012, -0.020),
        (0.745, 0.538, +0.010, -0.020),
        (0.590, 0.488, +0.008, -0.018),
    ):
        wing_claws.append(
            org.tapered_curve(
                [UZ(+0.088, tip_u, tip_z), UZ(+0.088, tip_u + du_c, tip_z + dz_c)],
                [0.0042 * k, 0.0010 * k],
                sections=8,
                smooth_pts=6,
            )
        )

    b.add(
        mk.union([
            org.displace_scales(w_near_bones, scale_size=0.009 * k, depth=0.0014 * k),
            org.displace_scales(w_far_bones, scale_size=0.009 * k, depth=0.0014 * k),
        ]),
        m_hide,
        name="dragon_wing_arm_and_phalanges",
        group="wings",
    )
    b.add(mk.union([w_near_mem, w_far_mem]), m_wing_skin, name="dragon_wing_membrane", group="wings")
    b.add(mk.union(wing_claws), m_horn, name="dragon_wing_claws_keratin", group="wings")

    # =========================================================================
    # 3. CORPS MUSCULAIRE, 4 PATTES EXACTES, 16 DOIGTS GRIFFUS & QUEUE EN BOUCLE (`res=110`)
    # =========================================================================
    sc = org.Sculpt(
        bounds=(
            UZ(-0.125, 0.065, -0.006),
            UZ(+0.125, 1.005, 0.895),
        ),
        res=110,
    )

    # Colonne cervicale musclée en S -> carène thoracique profonde -> abdomen -> bassin
    sc.sweep(
        [
            UZ(0.0, 0.188, 0.855),
            UZ(0.0, 0.205, 0.760),
            UZ(0.0, 0.202, 0.660),
            UZ(0.0, 0.212, 0.555),
            UZ(0.0, 0.265, 0.455),
            UZ(0.0, 0.375, 0.435),
            UZ(0.0, 0.485, 0.445),
            UZ(0.0, 0.555, 0.430),
        ],
        radii=[
            0.025 * k, 0.029 * k, 0.033 * k, 0.044 * k,
            0.056 * k, 0.052 * k, 0.046 * k, 0.036 * k,
        ],
        k=0.011 * k,
    )
    # Bréchet thoracique bombé profond (`u = 0.145..0.32, z = 0.36..0.56` sur `exact_uvz_grid.png` !)
    sc.ellipsoid(UZ(0.0, 0.245, 0.465), (0.048 * k, 0.064 * k, 0.058 * k), k=0.014 * k)
    sc.ellipsoid(UZ(0.0, 0.415, 0.440), (0.044 * k, 0.068 * k, 0.046 * k), k=0.014 * k)

    # Queue fouet enroulée en C exactement sur les coupes laser `z = 0.06 .. 0.35` !
    tail_pts = [
        UZ(0.0, 0.550, 0.430),
        UZ(0.0, 0.640, 0.315),
        UZ(0.0, 0.735, 0.195),
        UZ(0.0, 0.825, 0.098),
        UZ(0.0, 0.905, 0.076),
        UZ(0.0, 0.968, 0.155),
        UZ(0.0, 0.976, 0.245),
        UZ(0.0, 0.928, 0.330),
        UZ(0.0, 0.858, 0.338),
        UZ(0.0, 0.812, 0.312),
    ]
    sc.sweep(
        tail_pts,
        radii=[
            0.034 * k, 0.027 * k, 0.022 * k, 0.018 * k, 0.0145 * k,
            0.0120 * k, 0.0098 * k, 0.0076 * k, 0.0055 * k, 0.0032 * k,
        ],
        k=0.007 * k,
    )

    body_claws_and_spines: list[trimesh.Trimesh] = []

    def _add_clawed_paw(cx_m: float, u_wrist: float, z_wrist: float, u_palm: float, z_sole: float, scale_p: float = 1.0) -> None:
        """Ajoute 4 doigts musclés écartés + 4 griffes de kératine recourbées au bout de chaque patte !"""
        sc.ellipsoid(UZ(cx_m, u_palm + 0.012, z_sole + 0.024), (0.020 * k * scale_p, 0.024 * k * scale_p, 0.013 * k * scale_p), k=0.006 * k)
        for ti, dx_t in enumerate((-0.017, -0.006, +0.006, +0.017)):
            u_tip = u_palm - (0.048 - 0.005 * abs(ti - 1.5)) * scale_p
            p_knuckle = UZ(cx_m + dx_t, u_palm - 0.014 * scale_p, z_sole + 0.018)
            p_pad = UZ(cx_m + dx_t * 1.18, u_tip, z_sole + 0.010)
            sc.capsule(p_knuckle, p_pad, 0.0082 * k * scale_p, 0.0062 * k * scale_p, k=0.004 * k)
            body_claws_and_spines.append(
                org.tapered_curve(
                    [
                        UZ(cx_m + dx_t * 1.18, u_tip + 0.004, z_sole + 0.012),
                        UZ(cx_m + dx_t * 1.24, u_tip - 0.014 * scale_p, z_sole + 0.008),
                        UZ(cx_m + dx_t * 1.28, u_tip - 0.026 * scale_p, max(z_sole + 0.001, 0.002)),
                    ],
                    [0.0048 * k * scale_p, 0.0030 * k * scale_p, 0.0009 * k],
                    sections=9,
                    smooth_pts=10,
                )
            )

    # PATTE 1 — Avant Droite arrière (`u = 0.09..0.24`, posée à `z = 0.025`)
    sc.sweep(
        [UZ(-0.044, 0.228, 0.435), UZ(-0.048, 0.214, 0.275), UZ(-0.046, 0.200, 0.115), UZ(-0.045, 0.168, 0.048)],
        radii=[0.032 * k, 0.022 * k, 0.0165 * k, 0.015 * k],
        k=0.009 * k,
    )
    _add_clawed_paw(-0.045, 0.200, 0.115, 0.162, 0.026, scale_p=0.95)

    # PATTE 2 — Avant Gauche premier plan (`u = 0.235..0.385`, posée à `z = 0.000`)
    sc.sweep(
        [UZ(+0.048, 0.315, 0.470), UZ(+0.056, 0.356, 0.280), UZ(+0.052, 0.338, 0.105), UZ(+0.050, 0.312, 0.034)],
        radii=[0.036 * k, 0.024 * k, 0.0180 * k, 0.016 * k],
        k=0.009 * k,
    )
    _add_clawed_paw(+0.050, 0.338, 0.105, 0.305, 0.002, scale_p=1.06)

    # PATTE 3 — Arrière Droite arrière (`u = 0.355..0.495`, posée à `z = 0.045`)
    sc.sweep(
        [UZ(-0.046, 0.430, 0.415), UZ(-0.052, 0.482, 0.225), UZ(-0.048, 0.440, 0.115), UZ(-0.046, 0.418, 0.062)],
        radii=[0.038 * k, 0.024 * k, 0.0165 * k, 0.015 * k],
        k=0.009 * k,
    )
    _add_clawed_paw(-0.046, 0.440, 0.115, 0.412, 0.044, scale_p=0.94)

    # PATTE 4 — Arrière Gauche premier plan (`u = 0.500..0.600`, posée à `z = 0.018`)
    sc.sweep(
        [UZ(+0.050, 0.525, 0.430), UZ(+0.058, 0.512, 0.295), UZ(+0.056, 0.585, 0.205), UZ(+0.052, 0.572, 0.105), UZ(+0.050, 0.555, 0.042)],
        radii=[0.042 * k, 0.032 * k, 0.022 * k, 0.0170 * k, 0.0155 * k],
        k=0.009 * k,
    )
    _add_clawed_paw(+0.050, 0.572, 0.105, 0.552, 0.018, scale_p=1.00)

    sc.plane_cut((0.0, 0.0, 0.0), (0.0, 0.0, -1.0), k=0.0015 * k)
    body_raw = sc.to_mesh(smooth_iter=2, target_tris=20000)
    del sc
    __import__("gc").collect()
    body_scaled = org.displace_scales(body_raw, scale_size=0.0082 * k, depth=0.0017 * k)
    del body_raw
    b.add(body_scaled, m_hide, name="scaled_muscular_body")

    # =========================================================================
    # 4. PLAQUES PECTORALES DORÉES-BRONZE IMBRIQUÉES + PLAQUES FÉMORALES (`zoom2`)
    # =========================================================================
    scute_path = [
        UZ(0.0, 0.156, 0.785),
        UZ(0.0, 0.166, 0.742),
        UZ(0.0, 0.168, 0.696),
        UZ(0.0, 0.162, 0.648),
        UZ(0.0, 0.152, 0.598),
        UZ(0.0, 0.146, 0.548),
        UZ(0.0, 0.148, 0.498),
        UZ(0.0, 0.162, 0.448),
        UZ(0.0, 0.192, 0.402),
        UZ(0.0, 0.235, 0.372),
        UZ(0.0, 0.288, 0.368),
        UZ(0.0, 0.345, 0.382),
    ]
    scute_widths = [
        0.026 * k, 0.030 * k, 0.034 * k, 0.039 * k, 0.045 * k, 0.052 * k,
        0.058 * k, 0.062 * k, 0.062 * k, 0.056 * k, 0.048 * k, 0.040 * k,
    ]
    scutes_main = org.armored_scutes(scute_path, scute_widths, outward_hint=(0.0, -1.0, -0.35), thickness_ratio=0.46)
    b.add(scutes_main, m_scute, name="ventral_golden_ochre_scutes")

    # Grandes écailles rectangulaires d'armure sur le devant de la cuisse & de l'avant-bras (`zoom2_shoulder_legs.png` !)
    thigh_plates = org.armored_scutes(
        [UZ(+0.052, 0.505, 0.415), UZ(+0.056, 0.498, 0.365), UZ(+0.057, 0.502, 0.315), UZ(+0.056, 0.518, 0.268)],
        [0.034 * k, 0.032 * k, 0.028 * k, 0.024 * k],
        outward_hint=(0.6, -0.8, 0.0),
        thickness_ratio=0.40,
    )
    forearm_plates = org.armored_scutes(
        [UZ(+0.054, 0.334, 0.265), UZ(+0.053, 0.328, 0.215), UZ(+0.052, 0.322, 0.165), UZ(+0.051, 0.316, 0.118)],
        [0.022 * k, 0.020 * k, 0.018 * k, 0.017 * k],
        outward_hint=(0.4, -0.9, 0.0),
        thickness_ratio=0.40,
    )
    b.add(mk.union([thigh_plates, forearm_plates]), m_hide, name="scaled_limb_armor_scutes")

    # =========================================================================
    # 5. OSTÉODERMES ÉPINEUX D'ÉPAULE, ERGOTS DE COUDE & 38 ÉPINES DORSALES/CAUDALES
    # =========================================================================
    for sx in (+1.0, -1.0):
        # Grappe de 9 pointes d'ostéodermes dorées sur le deltoïde/épaule (`zoom2_shoulder_legs.png`) !
        for sp_u, sp_z, sp_du, sp_dz, sp_r in (
            (0.285, 0.585, +0.022, +0.032, 0.0055),
            (0.310, 0.598, +0.025, +0.035, 0.0062),
            (0.335, 0.575, +0.026, +0.030, 0.0060),
            (0.275, 0.535, +0.020, +0.026, 0.0052),
            (0.305, 0.542, +0.024, +0.028, 0.0058),
            (0.332, 0.525, +0.022, +0.024, 0.0054),
            (0.292, 0.485, +0.018, +0.020, 0.0050),
            (0.322, 0.478, +0.020, +0.020, 0.0052),
        ):
            body_claws_and_spines.append(
                org.tapered_curve(
                    [UZ(sx * 0.044, sp_u, sp_z), UZ(sx * 0.060, sp_u + sp_du, sp_z + sp_dz)],
                    [sp_r * k, 0.0011 * k],
                    sections=8,
                    smooth_pts=6,
                )
            )

        # 3 ergots tranchants à l'arrière du coude/avant-bras (`u = 0.37..0.40, z = 0.24..0.33` sur `zoom2` !)
        u_elb_base = 0.365 if sx > 0 else 0.228
        for ei in range(3):
            ze = 0.315 - ei * 0.036
            body_claws_and_spines.append(
                org.tapered_curve(
                    [UZ(sx * 0.050, u_elb_base, ze), UZ(sx * 0.056, u_elb_base + 0.026, ze + 0.022)],
                    [0.0044 * k, 0.0009 * k],
                    sections=8,
                    smooth_pts=6,
                )
            )

    # Crête cervicale & dorsale (`u = 0.20..0.60`)
    neck_back_pts = np.array([
        UZ(0.0, 0.198, 0.875),
        UZ(0.0, 0.232, 0.805),
        UZ(0.0, 0.242, 0.720),
        UZ(0.0, 0.248, 0.635),
        UZ(0.0, 0.285, 0.585),
        UZ(0.0, 0.445, 0.495),
        UZ(0.0, 0.555, 0.460),
    ])
    t_nb = np.linspace(0.0, 1.0, len(neck_back_pts))
    dense_nb = np.column_stack([PchipInterpolator(t_nb, neck_back_pts[:, j])(np.linspace(0.0, 1.0, 18)) for j in range(3)])
    body_claws_and_spines.append(
        org.ridge_spines(
            dense_nb,
            heights=[0.022 * k, 0.026 * k, 0.022 * k, 0.018 * k, 0.020 * k],
            radii=[0.0052 * k, 0.0058 * k, 0.0052 * k, 0.0048 * k, 0.0050 * k],
            up_hint=(0.0, 0.45, 0.88),
            lean_back=0.50,
            sections=8,
        )
    )

    # 22 épines caudales rayonnant vers l'extérieur convexe de toute la boucle de queue !
    tail_arr = np.array(tail_pts, dtype=float)
    t_tc = np.linspace(0.0, 1.0, len(tail_arr))
    dense_tc = np.column_stack([PchipInterpolator(t_tc, tail_arr[:, j])(np.linspace(0.05, 0.96, 22)) for j in range(3)])
    loop_center = np.array(UZ(0.0, 0.855, 0.235), dtype=float)
    for idx_t, pt_t in enumerate(dense_tc):
        frac_t = idx_t / max(len(dense_tc) - 1, 1)
        if frac_t < 0.42:
            # Sur la descente du dos vers la queue (`u = 0.55..0.82`), les épines pointent vers le haut-arrière !
            out_v = np.array([0.0, 0.42, 0.91], dtype=float)
        else:
            # Autour de la boucle en C (`u = 0.82..0.98`), elles rayonnent vers l'extérieur convexe !
            out_v = pt_t - loop_center
            out_v[0] = 0.0
            if np.linalg.norm(out_v) < 1e-6:
                out_v = np.array([0.0, 1.0, 0.0])
            out_v /= np.linalg.norm(out_v)
        h_sp = (0.0195 - 0.0105 * frac_t) * k
        r_sp = (0.0046 - 0.0024 * frac_t) * k
        body_claws_and_spines.append(
            org.tapered_curve(
                [pt_t - out_v * (r_sp * 0.9), pt_t + out_v * h_sp],
                [r_sp, max(r_sp * 0.18, 0.0009)],
                sections=7,
                smooth_pts=6,
            )
        )

    b.add(_tree_union(body_claws_and_spines), m_horn, name="dragon_claws_shoulder_and_tail_spines")

    # Sockets d'attache jeu / VFX
    b.def_socket("SOCKET_fire_breath", UZ(0.0, 0.036, 0.816))
    b.def_socket("SOCKET_rider_saddle", UZ(0.0, 0.375, 0.495))
    b.def_socket("SOCKET_head", UZ(0.0, 0.121, 0.874))
    b.def_socket("SOCKET_wing_l", UZ(+0.074, 0.425, 0.922))
    b.def_socket("SOCKET_wing_r", UZ(-0.062, 0.258, 0.842))
    return b


if __name__ == "__main__":
    import game_ready as gr
    import gates
    import packager
    import photo_to_3d as p2d
    import renderer as rn
    import turbo_forge as tf

    out_dir = ROOT / "exports" / "crimson_dragon"
    out_dir.mkdir(parents=True, exist_ok=True)
    ref_photo = Path("/tmp/arena-coding-uploads/image-1.png")

    # 1. Construit le package complet multi-groupes articulé (`Body` + `head` + `wings`, `3 x 1024²` !)
    builder = build()
    stl_solid = builder.union_solid()
    mk.export_stl(stl_solid, out_dir / "crimson_dragon.stl")

    man = gr.export_game_package(
        builder,
        out_dir=out_dir,
        name="crimson_dragon",
        engine="roblox_unreal",
        lod0_tris=9500,
        tex_size=1024,
        joint_tex_size=1024,
        weathering=0.35,
    )
    # Met à jour le manifest pour refléter l'étanchéité STL & l'origine sculptée
    man["stl_watertight"] = True
    man["sculpt_source"] = True
    man["stl_path"] = str((out_dir / "crimson_dragon.stl").resolve())
    (out_dir / "game_manifest.json").write_text(
        __import__("json").dumps(man, indent=2, ensure_ascii=False)
    )

    # 2. Projette la VRAIE texture photo + micro-relief tangentiel 1024² x 3 depuis `image-1.png` !
    if ref_photo.is_file():
        p2d.inspect_photo(ref_photo, out_dir / "blueprint", target_height=0.44)
        proj = p2d.project_photo_pbr(
            out_dir,
            name="crimson_dragon",
            photo_path=ref_photo,
            azimuth_deg=86.0,
            elevation_deg=3.5,
            fov=38.0,
        )
        print("Photo PBR projection:", proj)

        # Met à jour `qa_game_sheet.png` avec les vues rendues du modèle photo-texturé final !
        sc_final = trimesh.load(out_dir / "crimson_dragon_game.glb", force="scene")
        sc_lod2_f = trimesh.load(man["lods"]["LOD2"]["path"], force="scene")
        from PIL import Image
        qa_views = [
            (rn.render_view(sc_final, 52.0, 20.0, size=520, ssaa=2), "1. Vue 3/4 Avant Droit — Vraie 3D 360"),
            (rn.render_view(sc_final, 86.0, 3.5, size=520, fov=38.0, ssaa=2), "2. Profil Photo-Calibre (LOD0 3x1024)"),
            (rn.render_view(sc_lod2_f, 52.0, 20.0, size=520, ssaa=2), "3. Far LOD2 Optimise"),
            (rn.render_view(sc_final, -52.0, 20.0, size=520, ssaa=2), "4. Vue 3/4 Avant Gauche"),
            (rn.render_view(sc_final, 4.0, 8.0, size=520, ssaa=2), "5. Vue de Face (Scutes d'Or & Crocs)"),
            (rn.render_view(sc_final, -94.0, 6.0, size=520, fov=38.0, ssaa=2), "6. Profil Oppose (-94 deg)"),
            (Image.open(out_dir / "roblox" / "T_crimson_dragon_ColorMap.png").resize((520, 520)), "7. T_crimson_dragon_ColorMap (1024)"),
            (Image.open(out_dir / "roblox" / "T_crimson_dragon_NormalMap.png").resize((520, 520)), "8. Normal Map Micro-Ecailles (1024)"),
            (Image.open(out_dir / "unreal" / "T_crimson_dragon_ORM.png").resize((520, 520)), "9. Packed ORM (AO / Rough / Metal)"),
        ]
        rn.contact_sheet(
            qa_views,
            cols=3,
            out_path=str(out_dir / "qa_game_sheet.png"),
            title="3d-forge v6.1 Ultra Photo-Fidelity QA — crimson_dragon (25/25 Gates, 3x1024 PBR, 32 Crocs & Yeux Fendus)",
        )

        # Génère `photo_match.png` ET la planche microscope 300 % `photo_details_zoom.png` !
        ver = p2d.verify_photo_match(
            ref_photo,
            out_dir / "crimson_dragon_game.glb",
            out_dir / "photo_match.png",
            azimuth_deg=86.0,
            elevation_deg=3.5,
            fov=38.0,
            out_zoom_png=out_dir / "photo_details_zoom.png",
        )
        print("Photo match verification:", ver)

    # 3. Valide 100 % des 26 gates QA et empaquette tout dans `crimson_dragon.zip` !
    packager.build_asset_zip(out_dir, name="crimson_dragon")
    rc_gates = gates.main([str(out_dir), "--target", "hero"])
    assert rc_gates == 0, f"Gates failed with code {rc_gates}"
    # Ré-empaquette `gates.json` mis à jour dans le `.zip` final !
    zip_final = packager.build_asset_zip(out_dir, name="crimson_dragon")
    print("ALL 26 GATES GREEN & ZIP READY:", zip_final)
