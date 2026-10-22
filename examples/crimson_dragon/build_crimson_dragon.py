"""
build_crimson_dragon.py — Reconstruction 3D haute-fidélité du Dragon Rouge-Bronze Écailleux
directement mesurée sur le blueprint métrique de la photo de référence (`photo_to_3d.py inspect`) :
  - Hauteur `H = 0.440 m`, longueur `L = 0.569 m` (`L/H = 1.294`),
  - Cou élancé en S fier, crâne reptilien allongé ciselé, gueule entrouverte garnie de crocs,
  - Cornes occipitales recourbées + cornes jugales + crête sourcilière épineuse + yeux ambrés,
  - 14 plaques ventrales dorées-ocres imbriquées tangentes au cou/poitrail (`org.armored_scutes`),
  - Quadrupède athlétique musclé (épaules épineuses, cage thoracique, taille fine, pattes digitigrades
    posées à `z = 0` avec 16 griffes courbées),
  - Grandes ailes membraneuses cambrées à humérus musclé, griffe d'alula au poignet et 4 phalanges
    festonnées solides (`org.bat_wing`, zéro déchirure à la décimation),
  - Longue queue fouet enroulée en crochet complet derrière les pattes arrière + 40 épines dorsales,
  - Vraies écailles reptiliennes 3D gravées dans le maillage (`org.displace_scales`).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[2]
for _p in ("scripts", str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import meshkit as mk
import organic as org


def build(
    height: float = 0.44,
    scale_color: str = "#722b18",
    belly_color: str = "#c28c4c",
    wing_membrane_color: str = "#8a5236",
    horn_color: str = "#a67c56",
    eye_color: str = "#ff9914",
) -> mk.Builder:
    k = float(height) / 0.44
    b = mk.Builder("crimson_dragon", {"height": height})

    # Palette mesurée directement sur les pixels internes de la photo de référence
    m_hide = mk.mat.clay(scale_color, roughness=0.44)
    m_wing_skin = mk.mat.leather(wing_membrane_color, roughness=0.52)
    m_scute = mk.mat.clay(belly_color, roughness=0.38)
    m_horn = mk.mat.clay(horn_color, roughness=0.40)
    m_fang = mk.mat.enamel("#ebe0cc", roughness=0.20)
    m_eye = mk.mat.emissive(eye_color, strength=2.4)

    def P(x: float, y: float, z: float) -> tuple[float, float, float]:
        return (x * k, y * k, z * k)

    # =========================================================================
    # 1. CORPS MUSCLÉ ATHLÉTIQUE, COU FIER EN S, TÊTE DRACONIQUE & 4 MEMBRES (SDF HAUTE RÉSOLUTION)
    # =========================================================================
    sc = org.Sculpt(
        bounds=(P(-0.145, -0.305, -0.005), P(+0.145, +0.300, +0.445)),
        res=92,
    )

    # Colonne cervicale en S + cage thoracique profonde + taille fine + bassin félin
    neck_torso_spine = [
        P(0.0, -0.208, 0.376),  # base crâne
        P(0.0, -0.182, 0.340),  # haut du cou arqué
        P(0.0, -0.175, 0.285),  # creux dorsal du S
        P(0.0, -0.178, 0.230),  # base musclée du cou
        P(0.0, -0.146, 0.188),  # poitrail / sternum profond
        P(0.0, -0.088, 0.194),  # cage thoracique
        P(0.0, -0.022, 0.198),  # taille athlétique relevée
        P(0.0, +0.026, 0.190),  # croupe / bassin
    ]
    neck_torso_r = [0.027 * k, 0.029 * k, 0.032 * k, 0.039 * k, 0.056 * k, 0.053 * k, 0.041 * k, 0.046 * k]
    sc.sweep(neck_torso_spine, neck_torso_r, k=0.012 * k)

    # Relief pectoral & épaules musclées
    sc.ellipsoid(P(0.0, -0.158, 0.174), (0.048 * k, 0.054 * k, 0.048 * k), k=0.014 * k)
    sc.ellipsoid(P(0.052, -0.132, 0.202), (0.028 * k, 0.044 * k, 0.046 * k), k=0.012 * k, mirror_x=True)
    sc.ellipsoid(P(0.048, +0.012, 0.186), (0.030 * k, 0.048 * k, 0.048 * k), k=0.012 * k, mirror_x=True)

    # Crâne draconique allongé ciselé + mâchoire supérieure & inférieure entrouverte
    sc.ellipsoid(P(0.0, -0.214, 0.386), (0.027 * k, 0.038 * k, 0.025 * k), k=0.008 * k)
    sc.sweep(
        [P(0.0, -0.218, 0.386), P(0.0, -0.252, 0.372), P(0.0, -0.281, 0.358)],
        [0.024 * k, 0.018 * k, 0.0115 * k],
        k=0.006 * k,
    )
    # Mâchoire inférieure ouverte avec menton crochu
    sc.sweep(
        [P(0.0, -0.212, 0.366), P(0.0, -0.246, 0.351), P(0.0, -0.273, 0.343)],
        [0.019 * k, 0.0135 * k, 0.0085 * k],
        k=0.005 * k,
    )
    # Arcades sourcilières saillantes & crête zygomatique
    sc.sweep(
        [P(0.013, -0.264, 0.374), P(0.024, -0.236, 0.392), P(0.031, -0.198, 0.402)],
        [0.0055 * k, 0.0085 * k, 0.0095 * k],
        k=0.005 * k,
        mirror_x=True,
    )
    # Excavation nette de la gueule entrouverte
    sc.sweep(
        [P(0.0, -0.236, 0.360), P(0.0, -0.286, 0.350)],
        [0.0085 * k, 0.0075 * k],
        mode="sub",
        k=0.004 * k,
    )

    # Membres antérieurs musclés (légèrement décalés comme sur la photo : gauche avancé, droit en appui !)
    for sx, y_shift in ((+1.0, -0.028), (-1.0, +0.024)):
        f_leg = [
            P(sx * 0.052, -0.136 + y_shift * 0.35, 0.205),  # épaule
            P(sx * 0.058, -0.118 + y_shift * 0.55, 0.132),  # coude
            P(sx * 0.054, -0.146 + y_shift * 0.85, 0.058),  # poignet
            P(sx * 0.056, -0.172 + y_shift, 0.016),         # patte
            P(sx * 0.058, -0.196 + y_shift, 0.011),         # métatarse
        ]
        sc.sweep(f_leg, [0.027 * k, 0.021 * k, 0.0165 * k, 0.019 * k, 0.016 * k], k=0.009 * k)

    # Membres postérieurs digitigrades puissants en Z
    for sx, y_shift in ((+1.0, +0.026), (-1.0, -0.024)):
        h_leg = [
            P(sx * 0.050, +0.018 + y_shift * 0.30, 0.188),  # hanche
            P(sx * 0.064, -0.026 + y_shift * 0.55, 0.126),  # genou avancé
            P(sx * 0.060, +0.028 + y_shift * 0.75, 0.082),  # jarret arrière
            P(sx * 0.056, +0.016 + y_shift * 0.90, 0.026),  # cheville
            P(sx * 0.058, -0.012 + y_shift, 0.012),         # pied arrière
        ]
        sc.sweep(h_leg, [0.032 * k, 0.025 * k, 0.0185 * k, 0.016 * k, 0.0175 * k], k=0.009 * k)

    # Longue queue fouet sinueuse enroulée en crochet complet derrière les pattes arrière !
    tail_pts = [
        P(0.0, +0.032, 0.188),
        P(0.0, +0.092, 0.146),
        P(0.0, +0.160, 0.088),
        P(0.0, +0.224, 0.048),
        P(0.0, +0.268, 0.068),
        P(0.0, +0.278, 0.108),
        P(0.0, +0.248, 0.146),
        P(0.0, +0.192, 0.150),
        P(0.0, +0.160, 0.128),
    ]
    tail_r = [0.038 * k, 0.030 * k, 0.023 * k, 0.018 * k, 0.0145 * k, 0.0115 * k, 0.0085 * k, 0.0062 * k, 0.0042 * k]
    sc.sweep(tail_pts, tail_r, k=0.008 * k)

    # Semelle plane nette au niveau du sol `z = 0` sous les 4 pattes
    sc.plane_cut(P(0.0, 0.0, 0.001), (0.0, 0.0, -1.0), k=0.002 * k)

    body_mesh = sc.to_mesh(smooth_iter=3, target_tris=22000)
    # Gravure directe de vraies écailles reptiliennes 3D sur toute la peau !
    body_mesh = org.displace_scales(body_mesh, scale_size=0.0125 * k, depth=0.0019 * k, sharpness=1.5)
    b.add(body_mesh, m_hide, name="dragon_scaled_muscular_body")

    # =========================================================================
    # 2. PLAQUES VENTRALES DORÉES-OCRES IMBRIQUÉES TANGENTES AU COU & POITRAIL (`org.armored_scutes`)
    # =========================================================================
    scute_path = [
        P(0.0, -0.222, 0.348),
        P(0.0, -0.214, 0.326),
        P(0.0, -0.209, 0.302),
        P(0.0, -0.209, 0.278),
        P(0.0, -0.212, 0.252),
        P(0.0, -0.214, 0.226),
        P(0.0, -0.208, 0.198),
        P(0.0, -0.192, 0.170),
        P(0.0, -0.168, 0.146),
        P(0.0, -0.132, 0.136),
        P(0.0, -0.090, 0.142),
    ]
    scute_widths = [
        0.028 * k, 0.032 * k, 0.036 * k, 0.041 * k, 0.046 * k,
        0.052 * k, 0.060 * k, 0.066 * k, 0.068 * k, 0.060 * k, 0.050 * k,
    ]
    scutes = org.armored_scutes(scute_path, scute_widths, outward_hint=(0.0, -1.0, -0.35), thickness_ratio=0.48)
    b.add(scutes, m_scute, name="ventral_golden_ochre_scutes")

    # =========================================================================
    # 3. GRANDES AILES CHAUVE-SOURIS CAMBRÉES & FESTONNÉES (`org.bat_wing` SOLIDES SANS DÉCHIRURE)
    # =========================================================================
    wing_bones_all: list[trimesh.Trimesh] = []
    wing_mem_all: list[trimesh.Trimesh] = []
    claws_and_horns: list[trimesh.Trimesh] = []

    for sx in (+1.0, -1.0):
        # Bras d'aile musclé montant en diagonale tendue vers l'arrière-haut (`wr`) comme sur la photo !
        z_lift = 0.006 if sx < 0 else 0.0
        sh = P(sx * 0.038, -0.118, 0.242 + z_lift * 0.4)
        el = P(sx * 0.056, -0.092, 0.334 + z_lift * 0.7)
        wr = P(sx * 0.068, -0.068, 0.408 + z_lift)
        tips = [
            P(sx * 0.088, +0.284, 0.174 + z_lift),  # Rémige primaire externe longue
            P(sx * 0.098, +0.264, 0.242 + z_lift),  # 2e phalange
            P(sx * 0.092, +0.198, 0.246 + z_lift),  # 3e phalange
            P(sx * 0.074, +0.124, 0.232 + z_lift),  # 4e phalange interne
        ]
        flank = [
            sh,
            P(sx * 0.044, -0.060, 0.224),
            P(sx * 0.038, -0.004, 0.212),
        ]
        w_bones, w_mem, w_claw = org.bat_wing(
            shoulder=sh,
            elbow=el,
            wrist=wr,
            finger_tips=tips,
            body_anchors=flank,
            membrane_thickness=0.015 * k,
            camber=0.020 * k,
            arm_radius=0.022 * k,
            claw_len=0.042 * k,
        )
        wing_bones_all.append(w_bones)
        wing_mem_all.append(w_mem)
        claws_and_horns.append(w_claw)

    b.add(mk.union(wing_bones_all), m_hide, name="dragon_wing_arm_and_phalanges")
    b.add(mk.union(wing_mem_all), m_wing_skin, name="dragon_wing_membrane")

    # =========================================================================
    # 4. CORNES ROYALES RECOURBÉES, CRÊTE DORSALE/CAUDALE INTÉGRALE, CROCS, GRIFFES & YEUX AMBRÉS
    # =========================================================================
    for sx in (+1.0, -1.0):
        # Grande corne occipitale courbée en S relevée vers le ciel exactement comme sur la photo !
        main_horn = org.tapered_curve(
            [
                P(sx * 0.016, -0.204, 0.398),
                P(sx * 0.025, -0.172, 0.408),
                P(sx * 0.028, -0.145, 0.422),
                P(sx * 0.024, -0.128, 0.440),
            ],
            [0.0110 * k, 0.0080 * k, 0.0052 * k, 0.0018 * k],
            sections=16,
            smooth_pts=20,
        )
        # Corne temporale secondaire
        sec_horn = org.tapered_curve(
            [
                P(sx * 0.022, -0.198, 0.388),
                P(sx * 0.036, -0.168, 0.398),
                P(sx * 0.040, -0.148, 0.406),
            ],
            [0.0075 * k, 0.0050 * k, 0.0016 * k],
            sections=12,
            smooth_pts=14,
        )
        # Épines jugales de mâchoire + ostéodermes d'épaule
        jaw_spike = org.tapered_curve(
            [P(sx * 0.022, -0.206, 0.368), P(sx * 0.036, -0.184, 0.366)],
            [0.0062 * k, 0.0016 * k],
            sections=10,
            smooth_pts=10,
        )
        claws_and_horns.extend([main_horn, sec_horn, jaw_spike])

        for si_s in range(4):
            sh_sp = org.tapered_curve(
                [
                    P(sx * (0.056 + 0.004 * si_s), -0.150 + 0.016 * si_s, 0.196 + 0.014 * si_s),
                    P(sx * (0.072 + 0.004 * si_s), -0.136 + 0.018 * si_s, 0.214 + 0.016 * si_s),
                ],
                [0.0065 * k, 0.0018 * k],
                sections=8,
                smooth_pts=8,
            )
            claws_and_horns.append(sh_sp)

        # Œil reptilien ambré profondément enchâssé sous l'arcade sourcilière
        eye_orb = org.ellipsoid(0.0055 * k, 0.0085 * k, 0.0050 * k, subdivisions=2)
        mk.rot_y(eye_orb, sx * 16.0)
        b.add(eye_orb, m_eye, name=f"dragon_amber_eye_{'r' if sx > 0 else 'l'}", at=P(sx * 0.0185, -0.238, 0.382))

    # Pique mentonnière caractéristique sous le bout de la mâchoire inférieure
    chin_spike = org.tapered_curve(
        [P(0.0, -0.260, 0.346), P(0.0, -0.264, 0.330)],
        [0.0055 * k, 0.0015 * k],
        sections=10,
        smooth_pts=8,
    )
    claws_and_horns.append(chin_spike)

    # Rangées de crocs acérés supérieurs et inférieurs
    fangs_list: list[trimesh.Trimesh] = []
    for sx in (+1.0, -1.0):
        for ti in range(5):
            ty = -0.278 + ti * 0.0095
            tx = sx * (0.0072 + ti * 0.0016)
            f_up = org.tapered_curve(
                [P(tx, ty, 0.360 + ti * 0.0015), P(tx, ty, 0.351 + ti * 0.0015)],
                [0.0022 * k, 0.0007 * k],
                sections=8,
                smooth_pts=6,
            )
            f_lo = org.tapered_curve(
                [P(tx * 0.86, ty + 0.003, 0.345 + ti * 0.0012), P(tx * 0.86, ty + 0.003, 0.353 + ti * 0.0012)],
                [0.0019 * k, 0.0006 * k],
                sections=8,
                smooth_pts=6,
            )
            fangs_list.extend([f_up, f_lo])
    b.add(mk.union(fangs_list), m_fang, name="dragon_jaw_teeth_and_fangs")

    # 16 griffes courbées posées au sol aux 4 pattes
    for sx, y_sh in ((+1.0, -0.028), (-1.0, +0.024)):
        for ci, dx_c in enumerate((-0.014, -0.0045, +0.0045, +0.014)):
            cx = sx * 0.058 + dx_c
            cy = -0.194 + y_sh
            cl = org.tapered_curve(
                [P(cx, cy + 0.008, 0.013), P(cx, cy - 0.010, 0.011), P(cx, cy - 0.024, 0.003)],
                [0.0048 * k, 0.0032 * k, 0.0011 * k],
                sections=8,
                smooth_pts=10,
            )
            claws_and_horns.append(cl)

    for sx, y_sh in ((+1.0, +0.026), (-1.0, -0.024)):
        for ci, dx_c in enumerate((-0.014, -0.0045, +0.0045, +0.014)):
            cx = sx * 0.058 + dx_c
            cy = -0.012 + y_sh
            cl = org.tapered_curve(
                [P(cx, cy + 0.008, 0.012), P(cx, cy - 0.010, 0.010), P(cx, cy - 0.023, 0.003)],
                [0.0048 * k, 0.0032 * k, 0.0011 * k],
                sections=8,
                smooth_pts=10,
            )
            claws_and_horns.append(cl)

    # Crête continue de 34 épines orientées vers l'EXTÉRIEUR convexe du cou -> dos -> boucle caudale !
    neck_back_pts = np.array([
        P(0.0, -0.190, 0.382),
        P(0.0, -0.162, 0.342),
        P(0.0, -0.156, 0.285),
        P(0.0, -0.158, 0.236),
        P(0.0, -0.088, 0.232),
        P(0.0, -0.020, 0.228),
        P(0.0, +0.036, 0.212),
        P(0.0, +0.098, 0.164),
    ])
    from scipy.interpolate import PchipInterpolator
    t_nb = np.linspace(0.0, 1.0, len(neck_back_pts))
    dense_nb = np.column_stack([PchipInterpolator(t_nb, neck_back_pts[:, j])(np.linspace(0.0, 1.0, 16)) for j in range(3)])
    nb_spines = org.ridge_spines(
        dense_nb,
        heights=[0.020 * k, 0.025 * k, 0.019 * k, 0.022 * k, 0.017 * k],
        radii=[0.0052 * k, 0.0062 * k, 0.0052 * k, 0.0055 * k, 0.0045 * k],
        up_hint=(0.0, 0.20, 1.0),
        lean_back=0.45,
        sections=8,
    )
    claws_and_horns.append(nb_spines)

    # Épines caudales rayonnant vers l'extérieur du crochet `loop_center = P(0, 0.205, 0.105)` !
    tail_c_pts = np.array(tail_pts[2:], dtype=float)
    t_tc = np.linspace(0.0, 1.0, len(tail_c_pts))
    dense_tc = np.column_stack([PchipInterpolator(t_tc, tail_c_pts[:, j])(np.linspace(0.0, 1.0, 18)) for j in range(3)])
    loop_c = np.array(P(0.0, +0.205, 0.106), dtype=float)
    for idx_t in range(len(dense_tc)):
        pt_t = dense_tc[idx_t]
        out_dir_v = pt_t - loop_c
        out_dir_v[0] = 0.0
        out_dir_v /= max(float(np.linalg.norm(out_dir_v)), 1e-6)
        frac_t = idx_t / max(len(dense_tc) - 1, 1)
        h_sp = (0.0165 - 0.0075 * frac_t) * k
        r_sp = (0.0044 - 0.0020 * frac_t) * k
        claws_and_horns.append(
            org.tapered_curve(
                [pt_t - out_dir_v * (r_sp * 0.9), pt_t + out_dir_v * h_sp],
                [r_sp, max(r_sp * 0.18, 0.0012)],
                sections=7,
                smooth_pts=6,
            )
        )
    b.add(mk.union(claws_and_horns), m_horn, name="dragon_horns_claws_and_dorsal_spines")

    # Alignement exact sur le sol `z = 0.000`
    solid = b.union_solid()
    z0 = float(solid.bounds[0, 2])
    if abs(z0) > 1e-6:
        for mp, _, _ in b._parts:
            mp.apply_translation([0.0, 0.0, -z0])

    b.def_socket("SOCKET_breath_fire", P(0.0, -0.285, 0.352))
    b.def_socket("SOCKET_rider_saddle", P(0.0, -0.075, 0.245))
    return b


if __name__ == "__main__":
    import turbo_forge as tf
    import photo_to_3d as p2d
    import packager as pkg

    out_dir = Path("exports/crimson_dragon")
    man = tf.run_turbo(
        target=str(Path(__file__).resolve()),
        out_dir=out_dir,
        name="crimson_dragon",
        lod0_tris=9600,
        tex_size=1024,
        gate_target="hero",
    )
    ref_photo = Path("/tmp/arena-coding-uploads/image-1.png")
    if ref_photo.is_file():
        ver = p2d.verify_photo_match(
            ref_photo,
            out_dir / "crimson_dragon_game.glb",
            out_dir / "photo_match.png",
            azimuth_deg=+72.0,
            elevation_deg=8.0,
            fov=32.0,
        )
        print("Photo match verification:", ver)
        pkg.build_asset_zip(out_dir, name="crimson_dragon")
    print("ZIP bundle ready:", man["bundle_zip"])
