"""
characters.py — Figurines, bustes expressifs & créatures organiques 100 % CPU (`3d-forge`).

Démontre le standard d'excellence pour les personnages, mascottes et créatures sans aucun
outil GPU ni image externe (compatible **Claude.ai**, CLI et hors-ligne) :
  - volumes organiques fondus en continu via `mk.Sculpt` (argile SDF `C¹`),
  - accessoires nets séparés par matériau PBR (`mk.mat.skin`, `mk.mat.enamel`,
    `mk.mat.denim`, `mk.mat.leather`, `mk.mat.stone`) -> zéro bavage de couleur,
  - yeux multicouches expressifs (`sclère + iris + pupille + reflet de vie`),
  - visières et cornes courbées 3D (`mk.curved_visor`, `mk.tapered_curve`),
  - 100 % étanche (`is_watertight == True`) pour l'impression 3D ET Game-Ready (Roblox / UE5).
"""
from __future__ import annotations

import math
import meshkit as mk
import organic as org
from .registry import register


@register(
    "hero_bust",
    defaults={
        "height": 0.28,
        "cap_color": "#dc2626",
        "shirt_color": "#dc2626",
        "overalls_color": "#1d4ed8",
        "skin_color": "#f2a97e",
        "hair_color": "#4a2512",
        "eye_color": "#2563eb",
        "mustache": True,
    },
    info=[
        {"name": "height", "type": "float"},
        {"name": "cap_color", "type": "color"},
        {"name": "shirt_color", "type": "color"},
        {"name": "overalls_color", "type": "color"},
        {"name": "skin_color", "type": "color"},
        {"name": "hair_color", "type": "color"},
        {"name": "eye_color", "type": "color"},
        {"name": "mustache", "type": "bool"},
    ],
)
def build_hero_bust(
    height: float = 0.28,
    cap_color: str = "#dc2626",
    shirt_color: str = "#dc2626",
    overalls_color: str = "#1d4ed8",
    skin_color: str = "#f2a97e",
    hair_color: str = "#4a2512",
    eye_color: str = "#2563eb",
    mustache: bool = True,
) -> mk.Builder:
    """Buste expressif stylisé sur socle de galerie : casquette souple à visière courbée 3D,
    badge frontal en relief, visage sculpté lisse, yeux 4 couches, moustache 3D et bretelles."""
    s = float(height) / 0.28
    b = mk.Builder("hero_bust", {"height": height})

    m_skin = mk.mat.skin(skin_color, roughness=0.52)
    m_cap = mk.mat.fabric(cap_color, roughness=0.70)
    m_visor = mk.mat.enamel(cap_color, roughness=0.28)
    m_shirt = mk.mat.fabric(shirt_color, roughness=0.74)
    m_denim = mk.mat.denim(overalls_color, roughness=0.76)
    m_hair = mk.mat.clay(hair_color, roughness=0.68)
    m_badge = mk.mat.enamel("#f7f7f9", roughness=0.18)
    m_emblem = mk.mat.enamel(cap_color, roughness=0.18)
    m_gold = mk.mat.metal("#f2c94c", roughness=0.22, metallic=0.88)
    m_slate = mk.mat.stone("#262930", roughness=0.66)

    # 1. Socle de galerie étagé + bague laiton
    plinth_base, plinth_ring = org.museum_plinth(0.150 * s, 0.150 * s, 0.036 * s, round_profile=True)
    b.add(plinth_base, m_slate, name="plinth_stone")
    b.add(plinth_ring, m_gold, name="plinth_gold_ring")

    # 2. Buste épaules / torse sculpté en argile SDF douce
    torso_s = org.Sculpt(
        bounds=((-0.105 * s, -0.075 * s, 0.022 * s), (0.105 * s, 0.075 * s, 0.132 * s)),
        res=58,
    )
    torso_s.ellipsoid((0.0, 0.0, 0.072 * s), (0.088 * s, 0.056 * s, 0.052 * s))
    torso_s.capsule((-0.056 * s, 0.0, 0.082 * s), (0.056 * s, 0.0, 0.082 * s), 0.034 * s, k=0.016 * s)
    torso_s.plane_cut((0.0, 0.0, 0.026 * s), (0.0, 0.0, -1.0), k=0.004 * s)
    b.add(torso_s.to_mesh(smooth_iter=4, target_tris=2400), m_shirt, name="shirt_torso")

    # Plastron central + bretelles denim fusionnés en 1 pièce bleue ultra-propre !
    bib_s = org.Sculpt(
        bounds=((-0.075 * s, -0.070 * s, 0.022 * s), (0.075 * s, 0.070 * s, 0.125 * s)),
        res=56,
    )
    bib_s.ellipsoid((0.0, 0.0, 0.058 * s), (0.062 * s, 0.059 * s, 0.036 * s))
    for sx in (1.0, -1.0):
        pts_st = [
            (sx * 0.038 * s, -0.050 * s, 0.062 * s),
            (sx * 0.043 * s, -0.035 * s, 0.099 * s),
            (sx * 0.044 * s, 0.002 * s, 0.111 * s),
            (sx * 0.041 * s, 0.038 * s, 0.094 * s),
            (sx * 0.038 * s, 0.048 * s, 0.060 * s),
        ]
        for p_a, p_b in zip(pts_st[:-1], pts_st[1:]):
            bib_s.capsule(p_a, p_b, 0.0115 * s, 0.0115 * s, k=0.004 * s)
    bib_s.plane_cut((0.0, 0.0, 0.026 * s), (0.0, 0.0, -1.0), k=0.003 * s)
    b.add(bib_s.to_mesh(smooth_iter=3, target_tris=2200), m_denim, name="overalls_bib")

    for tag, sx in (("r", 1.0), ("l", -1.0)):
        btn = mk.cylinder(0.0115 * s, 0.010 * s, sections=28)
        mk.rot_x(btn, 90)
        b.add(btn, m_gold, name=f"gold_button_{tag}", at=(sx * 0.038 * s, -0.052 * s, 0.074 * s))

    collar = mk.cylinder(0.039 * s, 0.016 * s, sections=36)
    b.add(collar, m_shirt, name="shirt_collar", at=(0.0, -0.002 * s, 0.103 * s))

    # 3. Tête + cou + joues + menton + oreilles + nez sculptés d'un seul bloc continu !
    head_s = org.Sculpt(
        bounds=((-0.090 * s, -0.098 * s, 0.096 * s), (0.090 * s, 0.090 * s, 0.256 * s)),
        res=72,
    )
    head_s.capsule((0.0, 0.0, 0.100 * s), (0.0, -0.004 * s, 0.146 * s), 0.032 * s, 0.035 * s, k=0.012 * s)
    head_s.ellipsoid((0.0, 0.002 * s, 0.180 * s), (0.061 * s, 0.065 * s, 0.066 * s), k=0.016 * s)
    head_s.ellipsoid((0.034 * s, -0.034 * s, 0.156 * s), (0.030 * s, 0.028 * s, 0.025 * s), k=0.018 * s, mirror_x=True)
    head_s.ellipsoid((0.0, -0.038 * s, 0.136 * s), (0.028 * s, 0.026 * s, 0.020 * s), k=0.016 * s)
    # Oreilles rondes sculptées sans interférence capillaire + nez rond fondu
    head_s.ellipsoid((0.060 * s, 0.002 * s, 0.172 * s), (0.012 * s, 0.016 * s, 0.020 * s), k=0.006 * s, mirror_x=True)
    head_s.ellipsoid((0.065 * s, -0.002 * s, 0.172 * s), (0.006 * s, 0.008 * s, 0.010 * s), mode="sub", k=0.004 * s, mirror_x=True)
    head_s.ellipsoid((0.023 * s, -0.056 * s, 0.182 * s), (0.016 * s, 0.010 * s, 0.019 * s), mode="sub", k=0.007 * s, mirror_x=True)
    head_s.ellipsoid((0.0, -0.067 * s, 0.165 * s), (0.0195 * s, 0.023 * s, 0.016 * s), k=0.006 * s)
    b.add(head_s.to_mesh(smooth_iter=4, target_tris=4600), m_skin, name="head_skin")

    # 4. Yeux expressifs 4 couches + sourcils + moustache 3D
    org.add_stylized_eyes(
        b,
        center_y=-0.052 * s,
        center_z=0.181 * s,
        spacing_x=0.023 * s,
        radius=0.0148 * s,
        tall_scale=1.30,
        iris_color=eye_color,
        yaw_inward_deg=9.0,
    )

    for tag, sx in (("r", 1.0), ("l", -1.0)):
        brow = org.tapered_curve(
            [
                (sx * 0.009 * s, -0.057 * s, 0.200 * s),
                (sx * 0.023 * s, -0.058 * s, 0.206 * s),
                (sx * 0.037 * s, -0.051 * s, 0.200 * s),
            ],
            [0.0046 * s, 0.0056 * s, 0.0040 * s],
            sections=14,
        )
        b.add(brow, m_hair, name=f"eyebrow_{tag}")

    if mustache:
        for tag, sx in (("r", 1.0), ("l", -1.0)):
            stache = org.tapered_curve(
                [
                    (0.0, -0.062 * s, 0.151 * s),
                    (sx * 0.016 * s, -0.061 * s, 0.148 * s),
                    (sx * 0.032 * s, -0.054 * s, 0.150 * s),
                    (sx * 0.044 * s, -0.043 * s, 0.156 * s),
                ],
                [0.0088 * s, 0.0100 * s, 0.0088 * s, 0.0054 * s],
                sections=16,
            )
            b.add(stache, m_hair, name=f"mustache_{tag}")

    # 5. Cheveux sculptés (nuque & favoris devant l'oreille sans déborder dans le pavillon !)
    hair_s = org.Sculpt(
        bounds=((-0.072 * s, -0.028 * s, 0.128 * s), (0.072 * s, 0.082 * s, 0.215 * s)),
        res=50,
    )
    hair_s.ellipsoid((0.0, 0.026 * s, 0.172 * s), (0.061 * s, 0.050 * s, 0.040 * s))
    hair_s.ellipsoid((0.055 * s, -0.016 * s, 0.176 * s), (0.010 * s, 0.012 * s, 0.018 * s), k=0.008 * s, mirror_x=True)
    b.add(hair_s.to_mesh(smooth_iter=3, target_tris=1500), m_hair, name="hair_back")

    # 6. Casquette bouffante + visière 3D cintrée + médaillon blanc net & chevron "M"
    cap_s = org.Sculpt(
        bounds=((-0.082 * s, -0.082 * s, 0.184 * s), (0.082 * s, 0.086 * s, 0.285 * s)),
        res=58,
    )
    cap_s.ellipsoid((0.0, -0.002 * s, 0.224 * s), (0.068 * s, 0.072 * s, 0.034 * s))
    cap_s.ellipsoid((0.0, -0.012 * s, 0.244 * s), (0.062 * s, 0.066 * s, 0.030 * s), rot_deg=(-10.0, 0.0, 0.0), k=0.018 * s)
    cap_s.plane_cut((0.0, 0.0, 0.196 * s), (0.0, -0.16, -1.0), k=0.004 * s)
    cap_m = cap_s.to_mesh(smooth_iter=4, target_tris=2400)
    visor = org.curved_visor(
        width=0.114 * s,
        length=0.050 * s,
        thickness=0.011 * s,
        arch=0.018 * s,
        droop=0.009 * s,
        sections=26,
    )
    mk.place(visor, 0.0, -0.045 * s, 0.205 * s)
    b.add(mk.union([cap_m, visor]), m_visor, name="cap_crown_visor")

    badge = org.ellipsoid(0.019 * s, 0.008 * s, 0.019 * s, subdivisions=2)
    mk.rot_x(badge, -14.0)
    b.add(badge, m_badge, name="cap_badge", at=(0.0, -0.067 * s, 0.236 * s))

    emblem_m = org.tapered_curve(
        [
            (-0.0105 * s, -0.075 * s, 0.229 * s),
            (-0.0065 * s, -0.0775 * s, 0.242 * s),
            (0.0, -0.0765 * s, 0.234 * s),
            (0.0065 * s, -0.0775 * s, 0.242 * s),
            (0.0105 * s, -0.075 * s, 0.229 * s),
        ],
        [0.0029 * s, 0.0031 * s, 0.0029 * s, 0.0031 * s, 0.0029 * s],
        sections=8,
        smooth_pts=20,
    )
    b.add(emblem_m, m_emblem, name="cap_emblem")

    b.def_socket("SOCKET_head_top", (0.0, 0.0, 0.278 * s))
    return b


@register(
    "stylized_character",
    defaults={
        "height": 0.34,
        "jacket_color": "#e11d48",
        "pants_color": "#1e3a8a",
        "skin_color": "#f2a97e",
        "hair_color": "#3b2114",
        "boot_color": "#27272a",
    },
    info=[
        {"name": "height", "type": "float"},
        {"name": "jacket_color", "type": "color"},
        {"name": "pants_color", "type": "color"},
        {"name": "skin_color", "type": "color"},
        {"name": "hair_color", "type": "color"},
        {"name": "boot_color", "type": "color"},
    ],
)
def build_stylized_character(
    height: float = 0.34,
    jacket_color: str = "#e11d48",
    pants_color: str = "#1e3a8a",
    skin_color: str = "#f2a97e",
    hair_color: str = "#3b2114",
    boot_color: str = "#27272a",
) -> mk.Builder:
    """Personnage complet stylisé debout : bottes ancrées à z=0, veste à revers nets,
    T-shirt contrasté, mains, sourire, sourcils, frange balayée et sockets gameplay."""
    s = float(height) / 0.34
    b = mk.Builder("stylized_character", {"height": height})

    m_skin = mk.mat.skin(skin_color, roughness=0.52)
    m_jacket = mk.mat.enamel(jacket_color, roughness=0.36)
    m_shirt = mk.mat.fabric("#f5f5f7", roughness=0.74)
    m_pants = mk.mat.denim(pants_color, roughness=0.78)
    m_boot = mk.mat.leather(boot_color, roughness=0.46)
    m_sole = mk.mat.knobby_rubber("#f4f4f5", roughness=0.72)
    m_hair = mk.mat.clay(hair_color, roughness=0.66)
    m_mouth = mk.mat.clay("#9f1239", roughness=0.45)
    m_gold = mk.mat.metal("#eab308", roughness=0.24, metallic=0.88)

    # 1. Bottes posées à plat à z = 0 + jambes fuselées + bassin
    for tag, sx in (("r", 1.0), ("l", -1.0)):
        sole = mk.chamfer_box(0.038 * s, 0.062 * s, 0.011 * s, c=0.004 * s)
        b.add(sole, m_sole, name=f"boot_sole_{tag}", at=(sx * 0.030 * s, -0.008 * s, 0.0))

        boot_s = org.Sculpt(
            bounds=((-0.024 * s, -0.042 * s, 0.005 * s), (0.024 * s, 0.030 * s, 0.056 * s)),
            res=42,
        )
        boot_s.ellipsoid((0.0, -0.006 * s, 0.020 * s), (0.018 * s, 0.028 * s, 0.015 * s))
        boot_s.capsule((0.0, 0.004 * s, 0.018 * s), (0.0, 0.004 * s, 0.048 * s), 0.016 * s, 0.015 * s, k=0.008 * s)
        boot_s.plane_cut((0.0, 0.0, 0.006 * s), (0.0, 0.0, -1.0), k=0.002 * s)
        b.add(boot_s.to_mesh(smooth_iter=3, target_tris=1200), m_boot, name=f"boot_upper_{tag}",
              at=(sx * 0.030 * s, -0.004 * s, 0.0))

    pants_s = org.Sculpt(
        bounds=((-0.062 * s, -0.042 * s, 0.040 * s), (0.062 * s, 0.042 * s, 0.148 * s)),
        res=54,
    )
    for sx in (1.0, -1.0):
        pants_s.capsule((sx * 0.030 * s, -0.002 * s, 0.044 * s), (sx * 0.026 * s, 0.0, 0.118 * s), 0.016 * s, 0.020 * s, k=0.010 * s)
    pants_s.ellipsoid((0.0, 0.0, 0.122 * s), (0.043 * s, 0.031 * s, 0.022 * s), k=0.014 * s)
    b.add(pants_s.to_mesh(smooth_iter=4, target_tris=2400), m_pants, name="pants_legs")

    belt = mk.cylinder(0.042 * s, 0.012 * s, sections=36)
    belt.apply_scale([1.0, 0.74, 1.0])
    b.add(belt, m_boot, name="leather_belt", at=(0.0, 0.0, 0.128 * s))
    buckle = mk.chamfer_box(0.018 * s, 0.009 * s, 0.014 * s, c=0.002 * s)
    b.add(buckle, m_gold, name="gold_buckle", at=(0.0, -0.030 * s, 0.127 * s))

    # 2. T-shirt blanc central + veste ouverte à bords droits nets + col montant
    tee = org.superellipsoid(0.037 * s, 0.028 * s, 0.041 * s, e_xy=0.85, e_z=0.85)
    b.add(tee, m_shirt, name="inner_shirt", at=(0.0, -0.003 * s, 0.171 * s))

    jacket_s = org.Sculpt(
        bounds=((-0.088 * s, -0.048 * s, 0.132 * s), (0.088 * s, 0.048 * s, 0.222 * s)),
        res=58,
    )
    jacket_s.ellipsoid((0.0, 0.002 * s, 0.172 * s), (0.046 * s, 0.033 * s, 0.038 * s))
    jacket_s.round_box((0.0, -0.028 * s, 0.176 * s), (0.028 * s, 0.032 * s, 0.074 * s), r=0.004 * s, mode="sub", k=0.004 * s)
    for sx in (1.0, -1.0):
        jacket_s.capsule((sx * 0.042 * s, 0.0, 0.194 * s), (sx * 0.068 * s, -0.008 * s, 0.138 * s), 0.0155 * s, 0.0135 * s, k=0.010 * s)
    b.add(jacket_s.to_mesh(smooth_iter=4, target_tris=3000), m_jacket, name="hero_jacket")

    # Revers nets de veste encadrant proprement le T-shirt blanc
    for tag, sx in (("r", 1.0), ("l", -1.0)):
        lapel = org.tapered_curve(
            [
                (sx * 0.016 * s, -0.027 * s, 0.138 * s),
                (sx * 0.019 * s, -0.029 * s, 0.172 * s),
                (sx * 0.024 * s, -0.022 * s, 0.204 * s),
            ],
            [0.0055 * s, 0.0065 * s, 0.0060 * s],
            sections=14,
        )
        b.add(lapel, m_jacket, name=f"jacket_lapel_{tag}")

        hand = org.ellipsoid(0.013 * s, 0.015 * s, 0.015 * s, subdivisions=3)
        b.add(hand, m_skin, name=f"hand_skin_{tag}", at=(sx * 0.070 * s, -0.009 * s, 0.128 * s))
        b.def_socket(f"SOCKET_hand_{tag}", (sx * 0.072 * s, -0.018 * s, 0.124 * s))

    # 3. Tête stylisée + yeux 4 couches + sourcils + sourire + coiffure frange balayée
    head_s = org.Sculpt(
        bounds=((-0.068 * s, -0.068 * s, 0.198 * s), (0.068 * s, 0.068 * s, 0.318 * s)),
        res=64,
    )
    head_s.capsule((0.0, 0.0, 0.202 * s), (0.0, 0.0, 0.232 * s), 0.017 * s, 0.019 * s, k=0.008 * s)
    head_s.ellipsoid((0.0, 0.0, 0.262 * s), (0.047 * s, 0.048 * s, 0.046 * s), k=0.012 * s)
    head_s.ellipsoid((0.025 * s, -0.032 * s, 0.246 * s), (0.018 * s, 0.016 * s, 0.015 * s), k=0.012 * s, mirror_x=True)
    head_s.ellipsoid((0.046 * s, 0.002 * s, 0.258 * s), (0.008 * s, 0.011 * s, 0.014 * s), k=0.005 * s, mirror_x=True)
    head_s.ellipsoid((0.0, -0.047 * s, 0.250 * s), (0.0075 * s, 0.010 * s, 0.007 * s), k=0.004 * s)
    b.add(head_s.to_mesh(smooth_iter=4, target_tris=3400), m_skin, name="head_skin")

    org.add_stylized_eyes(
        b,
        center_y=-0.040 * s,
        center_z=0.259 * s,
        spacing_x=0.0185 * s,
        radius=0.0118 * s,
        tall_scale=1.22,
        iris_color="#0284c7",
        yaw_inward_deg=8.0,
    )

    for tag, sx in (("r", 1.0), ("l", -1.0)):
        brow = org.tapered_curve(
            [
                (sx * 0.009 * s, -0.044 * s, 0.275 * s),
                (sx * 0.019 * s, -0.045 * s, 0.279 * s),
                (sx * 0.029 * s, -0.040 * s, 0.274 * s),
            ],
            [0.0032 * s, 0.0038 * s, 0.0028 * s],
            sections=12,
        )
        b.add(brow, m_hair, name=f"eyebrow_{tag}")

    smile = org.tapered_curve(
        [
            (-0.011 * s, -0.043 * s, 0.239 * s),
            (0.0, -0.046 * s, 0.236 * s),
            (0.011 * s, -0.043 * s, 0.239 * s),
        ],
        [0.0022 * s, 0.0028 * s, 0.0022 * s],
        sections=12,
    )
    b.add(smile, m_mouth, name="smile_mouth")

    # Coiffure héroïque naturelle : casque capillaire + frange latérale balayée sur le front !
    hair_dome = org.Sculpt(
        bounds=((-0.064 * s, -0.062 * s, 0.240 * s), (0.064 * s, 0.066 * s, 0.334 * s)),
        res=56,
    )
    hair_dome.ellipsoid((0.0, 0.005 * s, 0.276 * s), (0.052 * s, 0.053 * s, 0.044 * s))
    hair_dome.ellipsoid((0.0, -0.025 * s, 0.252 * s), (0.041 * s, 0.032 * s, 0.030 * s), mode="sub", k=0.008 * s)
    # Mèches souples balayées vers la droite sur le haut du front (silhouette anime/Pixar)
    hair_dome.capsule((-0.028 * s, -0.034 * s, 0.294 * s), (-0.014 * s, -0.046 * s, 0.279 * s), 0.013 * s, 0.006 * s, k=0.008 * s)
    hair_dome.capsule((-0.006 * s, -0.036 * s, 0.298 * s), (0.012 * s, -0.048 * s, 0.281 * s), 0.014 * s, 0.006 * s, k=0.008 * s)
    hair_dome.capsule((0.016 * s, -0.032 * s, 0.296 * s), (0.034 * s, -0.042 * s, 0.282 * s), 0.012 * s, 0.005 * s, k=0.008 * s)
    b.add(hair_dome.to_mesh(smooth_iter=4, target_tris=2800), m_hair, name="hair_volume")

    b.def_socket("SOCKET_head", (0.0, 0.0, 0.326 * s))
    return b


@register(
    "dragon_creature",
    defaults={
        "height": 0.30,
        "scale_color": "#1e2430",
        "belly_color": "#d4a034",
        "horn_color": "#e5dac0",
        "eye_color": "#f59e0b",
    },
    info=[
        {"name": "height", "type": "float"},
        {"name": "scale_color", "type": "color"},
        {"name": "belly_color", "type": "color"},
        {"name": "horn_color", "type": "color"},
        {"name": "eye_color", "type": "color"},
    ],
)
def build_dragon_creature(
    height: float = 0.44,
    scale_color: str = "#6d2918",
    belly_color: str = "#b58348",
    horn_color: str = "#c9ae8c",
    eye_color: str = "#ff9914",
) -> mk.Builder:
    """Dragon quadrupède ailé complet haute-fidélité : cou fier en S, crâne ciselé à crocs,
    plaques pectorales imbriquées (`armored_scutes`), grandes ailes membraneuses solides (`bat_wing`),
    queue fouet enroulée à 32 épines dorsales et vraies écailles 3D (`displace_scales`)."""
    from pathlib import Path as _Path
    import importlib.util as _ilu

    spec = _ilu.spec_from_file_location(
        "_crimson_dragon_ref",
        str(_Path(__file__).resolve().parents[2] / "examples" / "crimson_dragon" / "build_crimson_dragon.py"),
    )
    mod = _ilu.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    b = mod.build(
        height=height,
        scale_color=scale_color,
        belly_color=belly_color,
        horn_color=horn_color,
        eye_color=eye_color,
    )
    b.name = "dragon_creature"
    return b


@register(
    "tengu_mask",
    defaults={
        "height": 0.25,
        "lacquer_color": "#a61c1c",
        "accent_black": "#171619",
        "gold_color": "#e0b33c",
        "cord_color": "#5c2c24",
    },
    info=[
        {"name": "height", "type": "float"},
        {"name": "lacquer_color", "type": "color"},
        {"name": "accent_black", "type": "color"},
        {"name": "gold_color", "type": "color"},
        {"name": "cord_color", "type": "color"},
    ],
)
def build_tengu_mask(
    height: float = 0.25,
    lacquer_color: str = "#a61c1c",
    accent_black: str = "#171619",
    gold_color: str = "#e0b33c",
    cord_color: str = "#5c2c24",
) -> mk.Builder:
    """Masque japonais traditionnel *Kurama Dai-Tengu* en bois sculpté laqué *urushi* :
    front bombé ridé, arcades sourcilières kabuki froncées, pommettes saillantes, plis
    nasogéniens profonds, long nez fier aux narines sculptées, yeux dorés obliques,
    crocs d'ivoire, bandeau *hachimaki* noir & or, envers concave creux laqué noir sans
    aucun dépassement interne (`trim_inside`), œillets latéraux et cordon *himo* tressé."""
    s = float(height) / 0.25
    b = mk.Builder("tengu_mask")

    m_red = mk.mat.lacquer(lacquer_color, roughness=0.22)
    m_black = mk.mat.lacquer(accent_black, roughness=0.26)
    m_inner = mk.mat.wood("#1e1b1a", roughness=0.78)
    m_gold = mk.mat.metal(gold_color, roughness=0.20, metallic=0.92)
    m_pupil = mk.mat.eye_gloss("#0b0c0e")
    m_fang = mk.mat.enamel("#f3ede0", roughness=0.16)
    m_cord = mk.mat.fabric(cord_color, roughness=0.82)

    # 1. Sculpture SDF C¹ complète du masque en bois d'hinoki (face + nez + rides + cavités)
    sc = org.Sculpt(
        bounds=((-0.106 * s, -0.188 * s, -0.012 * s), (0.106 * s, 0.042 * s, 0.262 * s)),
        res=82,
    )
    # Volume crânien frontal & mâchoire anguleuse
    sc.ellipsoid((0.0, -0.008 * s, 0.158 * s), (0.078 * s, 0.055 * s, 0.088 * s), k=0.010 * s)
    sc.ellipsoid((0.0, -0.012 * s, 0.078 * s), (0.060 * s, 0.047 * s, 0.066 * s), k=0.018 * s)
    sc.sweep(
        [(0.0, -0.034 * s, 0.034 * s), (0.0, -0.045 * s, 0.015 * s)],
        [0.024 * s, 0.015 * s],
        k=0.012 * s,
    )
    sc.sweep(
        [(0.056 * s, -0.004 * s, 0.094 * s), (0.038 * s, -0.026 * s, 0.038 * s), (0.014 * s, -0.040 * s, 0.017 * s)],
        [0.015 * s, 0.013 * s, 0.011 * s],
        k=0.012 * s,
        mirror_x=True,
    )

    # Pommettes zygomatiques hautes + creux des joues tendues
    sc.sweep(
        [(0.025 * s, -0.043 * s, 0.128 * s), (0.056 * s, -0.033 * s, 0.136 * s), (0.075 * s, -0.007 * s, 0.150 * s)],
        [0.014 * s, 0.018 * s, 0.012 * s],
        k=0.013 * s,
        mirror_x=True,
    )
    sc.ellipsoid(
        (0.052 * s, -0.036 * s, 0.088 * s),
        (0.017 * s, 0.012 * s, 0.021 * s),
        mode="sub",
        k=0.010 * s,
        mirror_x=True,
    )

    # Arcades sourcilières kabuki féroces + rides verticales de glabelle
    sc.sweep(
        [(0.008 * s, -0.053 * s, 0.155 * s), (0.034 * s, -0.051 * s, 0.169 * s), (0.065 * s, -0.031 * s, 0.178 * s)],
        [0.011 * s, 0.014 * s, 0.009 * s],
        k=0.008 * s,
        mirror_x=True,
    )
    sc.sweep(
        [(0.007 * s, -0.058 * s, 0.160 * s), (0.009 * s, -0.053 * s, 0.194 * s)],
        [0.0034 * s, 0.0024 * s],
        mode="sub",
        k=0.003 * s,
        mirror_x=True,
    )

    # Orbites obliques profondes en amande
    sc.sweep(
        [(0.019 * s, -0.052 * s, 0.141 * s), (0.036 * s, -0.048 * s, 0.148 * s), (0.055 * s, -0.036 * s, 0.156 * s)],
        [0.0095 * s, 0.0122 * s, 0.0085 * s],
        mode="sub",
        k=0.0045 * s,
        mirror_x=True,
    )

    # Long nez fier de Kurama Dai-Tengu (projeté droit en avant avec arête sculptée + narines)
    sc.sweep(
        [
            (0.0, -0.036 * s, 0.148 * s),
            (0.0, -0.086 * s, 0.145 * s),
            (0.0, -0.135 * s, 0.137 * s),
            (0.0, -0.171 * s, 0.127 * s),
        ],
        [0.0215 * s, 0.0185 * s, 0.0168 * s, 0.0142 * s],
        k=0.012 * s,
    )
    sc.ellipsoid((0.017 * s, -0.058 * s, 0.115 * s), (0.012 * s, 0.014 * s, 0.010 * s), k=0.007 * s, mirror_x=True)
    sc.ellipsoid(
        (0.014 * s, -0.062 * s, 0.107 * s),
        (0.0052 * s, 0.0075 * s, 0.0048 * s),
        mode="sub",
        k=0.0025 * s,
        mirror_x=True,
    )

    # Plis nasogéniens du rictus + bouche ouverte grimaçante + lèvres sculptées
    sc.sweep(
        [(0.022 * s, -0.052 * s, 0.112 * s), (0.040 * s, -0.044 * s, 0.082 * s), (0.044 * s, -0.034 * s, 0.052 * s)],
        [0.0075 * s, 0.0082 * s, 0.0055 * s],
        k=0.006 * s,
        mirror_x=True,
    )
    sc.sweep(
        [(0.018 * s, -0.055 * s, 0.110 * s), (0.034 * s, -0.048 * s, 0.082 * s), (0.038 * s, -0.038 * s, 0.056 * s)],
        [0.0030 * s, 0.0034 * s, 0.0024 * s],
        mode="sub",
        k=0.003 * s,
        mirror_x=True,
    )
    sc.sweep(
        [
            (-0.034 * s, -0.047 * s, 0.062 * s),
            (-0.018 * s, -0.054 * s, 0.071 * s),
            (0.0, -0.056 * s, 0.073 * s),
            (0.018 * s, -0.054 * s, 0.071 * s),
            (0.034 * s, -0.047 * s, 0.062 * s),
        ],
        [0.0095 * s, 0.0145 * s, 0.0155 * s, 0.0145 * s, 0.0095 * s],
        mode="sub",
        k=0.004 * s,
    )
    sc.sweep(
        [(0.0, -0.052 * s, 0.086 * s), (0.020 * s, -0.050 * s, 0.083 * s), (0.037 * s, -0.042 * s, 0.068 * s)],
        [0.0072 * s, 0.0068 * s, 0.0048 * s],
        k=0.005 * s,
        mirror_x=True,
    )
    sc.sweep(
        [(0.0, -0.049 * s, 0.046 * s), (0.019 * s, -0.047 * s, 0.049 * s), (0.035 * s, -0.040 * s, 0.058 * s)],
        [0.0078 * s, 0.0070 * s, 0.0048 * s],
        k=0.005 * s,
        mirror_x=True,
    )

    # Oreilles pointues de Tengu sculptées sur les tempes
    sc.sweep(
        [(0.073 * s, 0.004 * s, 0.116 * s), (0.087 * s, 0.010 * s, 0.150 * s), (0.091 * s, 0.018 * s, 0.184 * s)],
        [0.010 * s, 0.013 * s, 0.006 * s],
        k=0.008 * s,
        mirror_x=True,
    )

    # Découpe plane franche du rebord arrière du masque (`y <= +0.022`)
    sc.round_box((0.0, 0.078 * s, 0.125 * s), (0.28 * s, 0.112 * s, 0.34 * s), r=0.004 * s, mode="sub", k=0.004 * s)
    outer_face = sc.to_mesh(smooth_iter=4, target_tris=6400)

    # 2. Cavité anatomique concave d'envers (chevauchement solide 3 mm -> 100 % étanche !)
    cav_red = org.Sculpt(
        bounds=((-0.095 * s, -0.075 * s, 0.004 * s), (0.095 * s, 0.095 * s, 0.244 * s)),
        res=56,
    )
    cav_red.ellipsoid((0.0, 0.013 * s, 0.150 * s), (0.066 * s, 0.051 * s, 0.076 * s), k=0.010 * s)
    cav_red.ellipsoid((0.0, 0.009 * s, 0.082 * s), (0.049 * s, 0.043 * s, 0.054 * s), k=0.014 * s)
    cav_red.ellipsoid((0.0, -0.019 * s, 0.136 * s), (0.017 * s, 0.034 * s, 0.021 * s), k=0.010 * s)
    cav_red.round_box((0.0, 0.056 * s, 0.125 * s), (0.146 * s, 0.076 * s, 0.216 * s), r=0.010 * s, k=0.010 * s)
    cutter_red = cav_red.to_mesh(smooth_iter=3, target_tris=2200)

    cav_open = org.Sculpt(
        bounds=((-0.095 * s, -0.075 * s, 0.004 * s), (0.095 * s, 0.095 * s, 0.244 * s)),
        res=56,
    )
    cav_open.ellipsoid((0.0, 0.017 * s, 0.150 * s), (0.063 * s, 0.048 * s, 0.073 * s), k=0.010 * s)
    cav_open.ellipsoid((0.0, 0.013 * s, 0.082 * s), (0.046 * s, 0.040 * s, 0.051 * s), k=0.014 * s)
    cav_open.ellipsoid((0.0, -0.015 * s, 0.136 * s), (0.015 * s, 0.031 * s, 0.019 * s), k=0.010 * s)
    cav_open.round_box((0.0, 0.058 * s, 0.125 * s), (0.142 * s, 0.076 * s, 0.212 * s), r=0.010 * s, k=0.010 * s)
    cutter_open = cav_open.to_mesh(smooth_iter=3, target_tris=2200)

    # Doublure intérieure noire mate à chevauchement franc de 3 mm dans la coque rouge !
    cav_liner = org.Sculpt(
        bounds=((-0.095 * s, -0.075 * s, 0.004 * s), (0.095 * s, 0.095 * s, 0.244 * s)),
        res=52,
    )
    cav_liner.ellipsoid((0.0, 0.010 * s, 0.150 * s), (0.069 * s, 0.054 * s, 0.079 * s), k=0.010 * s)
    cav_liner.ellipsoid((0.0, 0.006 * s, 0.082 * s), (0.052 * s, 0.046 * s, 0.057 * s), k=0.014 * s)
    cav_liner.ellipsoid((0.0, -0.022 * s, 0.136 * s), (0.019 * s, 0.037 * s, 0.023 * s), k=0.010 * s)
    liner_outer = cav_liner.to_mesh(smooth_iter=3, target_tris=2000)
    liner_shell = mk.difference(mk.intersection(outer_face, liner_outer), [cutter_open])

    b.add(outer_face, m_red, name="mask_urushi_shell")

    # 3. Fond de bouche noir profond + dents & crocs d'ivoire + yeux dorés + poils urushi en relief net
    mouth_bg = org.ellipsoid(0.034 * s, 0.016 * s, 0.016 * s, center=(0.0, -0.040 * s, 0.068 * s))
    b.add(mouth_bg, m_black, name="mouth_interior")

    for tx in (-0.013, -0.0045, 0.0045, 0.013):
        tooth_u = org.ellipsoid(0.0042 * s, 0.0042 * s, 0.0055 * s, center=(tx * s, -0.049 * s, 0.078 * s))
        b.add(tooth_u, m_fang, name=f"tooth_up_{tx:+.3f}")

    # Yeux dorés sculptés C² à pupille concave strictement interne (0,00 mm de protubérance !)
    org.add_sculpted_eyes(
        b,
        center_y=-0.045 * s,
        center_z=0.148 * s,
        spacing_x=0.036 * s,
        rx=0.0156 * s,
        ry=0.0096 * s,
        rz=0.0082 * s,
        pupil_radius=0.0044 * s,
        pupil_recess=0.0018 * s,
        tilt_deg=16.0,
        yaw_deg=10.0,
        iris_mat=m_gold,
        pupil_mat=m_pupil,
        eyelid_mat=m_black,
    )

    for sx, tag in ((-1.0, "l"), (1.0, "r")):
        # Sourcils touffus Kabuki relevés en flamme bien en relief devant l'arcade
        brow = org.tapered_curve(
            [
                (sx * 0.009 * s, -0.059 * s, 0.159 * s),
                (sx * 0.033 * s, -0.059 * s, 0.173 * s),
                (sx * 0.058 * s, -0.045 * s, 0.185 * s),
                (sx * 0.076 * s, -0.025 * s, 0.197 * s),
            ],
            [0.0062 * s, 0.0094 * s, 0.0080 * s, 0.0032 * s],
            sections=14,
        )
        b.add(brow, m_black, name=f"eyebrow_{tag}")

        # Moustache effilée relevée en croc bien saillante
        stache = org.tapered_curve(
            [
                (sx * 0.005 * s, -0.058 * s, 0.095 * s),
                (sx * 0.024 * s, -0.056 * s, 0.091 * s),
                (sx * 0.046 * s, -0.045 * s, 0.081 * s),
                (sx * 0.065 * s, -0.029 * s, 0.088 * s),
            ],
            [0.0058 * s, 0.0076 * s, 0.0058 * s, 0.0024 * s],
            sections=14,
        )
        b.add(stache, m_black, name=f"mustache_{tag}")

        # Crocs supérieurs (vers le bas) & crocs inférieurs (vers le haut)
        fang_up = org.tapered_curve(
            [
                (sx * 0.024 * s, -0.049 * s, 0.081 * s),
                (sx * 0.025 * s, -0.053 * s, 0.061 * s),
            ],
            [0.0056 * s, 0.0015 * s],
            sections=14,
        )
        b.add(fang_up, m_fang, name=f"fang_upper_{tag}")

        fang_lo = org.tapered_curve(
            [
                (sx * 0.018 * s, -0.048 * s, 0.052 * s),
                (sx * 0.019 * s, -0.052 * s, 0.068 * s),
            ],
            [0.0046 * s, 0.0014 * s],
            sections=14,
        )
        b.add(fang_lo, m_fang, name=f"fang_lower_{tag}")

    # Barbiche sculptée de menton (*顎鬚*) bien en relief
    goatee = org.tapered_curve(
        [
            (0.0, -0.050 * s, 0.038 * s),
            (0.0, -0.055 * s, 0.020 * s),
            (0.0, -0.048 * s, 0.004 * s),
        ],
        [0.0085 * s, 0.0072 * s, 0.0028 * s],
        sections=14,
    )
    b.add(goatee, m_black, name="chin_beard")

    # Bandeau frontal continu noir & double filet d'or (*鉢巻*) épousant tout le galbe du front !
    band_pts = [
        (-0.078 * s, 0.003 * s, 0.194 * s),
        (-0.048 * s, -0.039 * s, 0.200 * s),
        (0.0, -0.054 * s, 0.204 * s),
        (0.048 * s, -0.039 * s, 0.200 * s),
        (0.078 * s, 0.003 * s, 0.194 * s),
    ]
    b.add(org.tapered_curve(band_pts, [0.0072 * s, 0.0088 * s, 0.0092 * s, 0.0088 * s, 0.0072 * s], sections=18),
          m_black, name="headband_black")
    gold_pts = [(p[0], p[1] - 0.0030 * s, p[2] + 0.0068 * s) for p in band_pts]
    b.add(org.tapered_curve(gold_pts, [0.0032 * s, 0.0038 * s, 0.0042 * s, 0.0038 * s, 0.0032 * s], sections=18),
          m_gold, name="headband_gold_trim")

    # 4. Évidement booléen global (`trim_inside`) + doublure noire à chevauchement 3 mm !
    b.trim_inside(cutter_red)
    if len(liner_shell.faces) > 0:
        b.add(liner_shell, m_inner, name="inner_lining")

    # 5. Œillets latéraux en laiton doré + cordon *himo* tressé passant UNIQUEMENT derrière la nuque
    for sx, tag in ((-1.0, "l"), (1.0, "r")):
        lug = mk.cylinder(0.0068 * s, 0.008 * s, sections=20)
        mk.rot_y(lug, 90.0)
        b.add(lug, m_gold, name=f"eyelet_{tag}", at=(sx * 0.076 * s, 0.012 * s, 0.126 * s))

    cord = org.tapered_curve(
        [
            (-0.079 * s, 0.013 * s, 0.126 * s),
            (-0.084 * s, 0.048 * s, 0.118 * s),
            (-0.048 * s, 0.076 * s, 0.106 * s),
            (0.0, 0.084 * s, 0.102 * s),
            (0.048 * s, 0.076 * s, 0.106 * s),
            (0.084 * s, 0.048 * s, 0.118 * s),
            (0.079 * s, 0.013 * s, 0.126 * s),
        ],
        [0.0034 * s, 0.0038 * s, 0.0040 * s, 0.0040 * s, 0.0040 * s, 0.0038 * s, 0.0034 * s],
        sections=16,
    )
    b.add(cord, m_cord, name="cord_himo")

    # Mise à hauteur exacte `z_min = 0`
    sc_tmp = b.union_solid()
    z_shift = -float(sc_tmp.bounds[0][2])
    if abs(z_shift) > 1e-6:
        for mesh_p, _, _ in b._parts:
            mesh_p.apply_translation([0.0, 0.0, z_shift])

    b.def_socket("SOCKET_head_wear", (0.0, 0.010 * s, 0.130 * s + z_shift))
    return b

