"""Recettes props : sword, rocket, house, tree, car, motocross.
Utilise CSG (différences) pour les détails incrustés (niches de roues, fenêtres)."""
from __future__ import annotations
import math
import numpy as np
from .registry import register
import meshkit as mk


@register("sword", defaults={"length": 0.9, "blade_color": "steel",
                             "guard_color": "brass"},
          info=[{"name": "length", "type": "float", "help": "Longueur totale en m"},
                {"name": "blade_color", "type": "choice",
                 "choices": ["steel", "silver", "aluminum", "chrome", "gold"]},
                {"name": "guard_color", "type": "choice",
                 "choices": ["brass", "bronze", "copper", "gold"]}])
def build_sword(length=0.9, blade_color="steel", guard_color="brass"):
    b = mk.Builder("sword", {})
    blade_m = mk.mat.named_metal(blade_color, 0.20)
    guard_m = mk.mat.named_metal(guard_color, 0.32)
    grip_m = mk.mat.rubber("#3b2a1c", 0.75)

    grip_h = length * 0.14
    guard_z = grip_h + 0.008

    # Pommeau en disque chanfreiné + fusée elliptique traversante + quillons arrondis (0 vide !)
    pommel = mk.cylinder(0.022, 0.014, sections=36)
    mk.rot_x(pommel, 90)
    mk.place(pommel, 0, 0.007, 0.022)
    b.add(pommel, guard_m, name="pommel")

    grip = mk.capsule(0.0125, grip_h + 0.016)
    mk.scale(grip, (1.15, 0.78, 1.0))
    b.add(grip, grip_m, name="grip", at=(0, 0, 0.014))

    guard = mk.rounded_box(0.145, 0.022, 0.018, r=0.0045)
    b.add(guard, guard_m, name="guard", at=(0, 0, guard_z))

    # Lame forgée losangique continue par extrude/loft 100 % manifold jusqu'à la pointe !
    z0_b = guard_z + 0.006
    n_st = 28
    rings = []
    for k, t in enumerate(np.linspace(0.0, 1.0, n_st)):
        w = 0.020 * (1.0 - 0.30 * t)
        if t > 0.86:
            w *= max(0.05, (1.0 - (t - 0.86) / 0.14) ** 0.85)
        th = 0.0044 * max(0.10, 1.0 - 0.55 * t)
        z = float(z0_b + (length - z0_b) * t)
        rings.append(np.array([[-w, 0.0, z], [0.0, -th, z], [w, 0.0, z], [0.0, th, z]]))
    blade_msh = mk.loft(rings, caps=True)
    b.add(blade_msh, blade_m, name="blade")
    fuller_h = (length - z0_b) * 0.62
    fuller = mk.chamfer_box(0.0062, 0.0104, fuller_h, c=0.0016)
    b.add(fuller, mk.mat.named_metal(blade_color, 0.42),
          name="fuller", at=(0, 0, z0_b + 0.012))
    return b


@register("katana", defaults={"length": 0.98, "sori": 0.018,
                              "ito_color": "#1c1e24", "same_color": "#dfd8c5",
                              "tsuba_color": "bronze", "textured": True},
          info=[{"name": "length", "type": "float", "help": "Longueur totale en m (~0.98 m)"},
                {"name": "sori", "type": "float", "help": "Courbure de lame en m (~0.018 m)"},
                {"name": "ito_color", "type": "color", "help": "Couleur du tressage tsuka-maki"},
                {"name": "same_color", "type": "color", "help": "Peau de raie sous le tressage"},
                {"name": "tsuba_color", "type": "choice",
                 "choices": ["bronze", "brass", "steel", "gold"]},
                {"name": "textured", "type": "bool",
                 "help": "Cuire l'atlas PBR complet (tsuka-maki losanges + hamon + usure)"}])
def build_katana(length=0.98, sori=0.018, ito_color="#1c1e24",
                 same_color="#dfd8c5", tsuba_color="bronze", textured=True):
    """Katana forgé (shinogi-zukuri) : lame courbée continue `sweep()`, kissaki
    biseauté, habaki laiton, seppa, tsuba ajourée, fuchi/kashira et tsuka
    tressée en losanges (bake PBR `diamond` + ligne de trempe `hamon`)."""
    b = mk.Builder("katana", {"sori": sori, "textured": textured})
    u = float(length) / 0.98

    steel_m = mk.mat.named_metal("steel", 0.20)
    brass_m = mk.mat.named_metal("brass", 0.26)
    tsuba_m = mk.mat.named_metal(tsuba_color, 0.42)
    lacquer_m = mk.mat.paint("#19191d", 0.28)
    ito_m = mk.mat.fabric(ito_color, 0.84)

    # 1. Kashira + Tsuka légèrement cintrée + Fuchi (0 -> 0.300 * u)
    kashira = mk.rounded_box(0.036 * u, 0.022 * u, 0.022 * u, r=0.006 * u)
    b.add(kashira, lacquer_m, name="kashira", at=(0, 0, 0.0))

    tsuka_path = [[0.0, 0.0, z * u] for z in np.linspace(0.018, 0.286, 20)]
    th_ang = np.linspace(0, 2 * math.pi, 28, endpoint=False)
    grip_prof = np.column_stack([0.0165 * u * np.cos(th_ang),
                                 0.0102 * u * np.sin(th_ang)])
    tsuka = mk.sweep(
        grip_prof,
        tsuka_path,
        scale=lambda t: (1.0 - 0.06 * math.sin(math.pi * t), 1.0 - 0.04 * math.sin(math.pi * t)),
    )
    b.add(tsuka, ito_m, name="tsuka")

    fuchi = mk.rounded_box(0.038 * u, 0.024 * u, 0.016 * u, r=0.004 * u)
    b.add(fuchi, lacquer_m, name="fuchi", at=(0, 0, 0.283 * u))

    # 2. Seppa + Tsuba ronde ajourée (CSG) + Seppa haut + Habaki laiton
    b.add(mk.rounded_box(0.042 * u, 0.026 * u, 0.004 * u, r=0.0012 * u),
          brass_m, name="seppa_low", at=(0, 0, 0.297 * u))

    tsuba = mk.cylinder(0.041 * u, 0.0065 * u, sections=56)
    mk.place(tsuba, 0, 0, 0.300 * u)
    cutouts = []
    for sx in (-1, 1):
        slot = mk.cylinder(0.0115 * u, 0.020 * u, sections=24)
        mk.scale(slot, (0.68, 1.25, 1.0))
        mk.place(slot, sx * 0.021 * u, 0, 0.294 * u)
        cutouts.append(slot)
    tsuba = mk.difference(tsuba, cutouts)
    b.add(tsuba, tsuba_m, name="tsuba")

    b.add(mk.rounded_box(0.042 * u, 0.026 * u, 0.004 * u, r=0.0012 * u),
          brass_m, name="seppa_top", at=(0, 0, 0.3055 * u))

    # Habaki profilé épousant déjà l'amorce trapézoïdale de la lame
    hab_prof = [(-0.0165 * u, 0.0), (-0.004 * u, 0.0052 * u),
                (0.0168 * u, 0.0012 * u), (-0.004 * u, -0.0052 * u)]
    habaki = mk.sweep(hab_prof, [[0.0, 0.0, 0.308 * u], [0.0, 0.0, 0.338 * u]],
                      scale=[(1.04, 1.06), (0.98, 0.98)])
    b.add(habaki, brass_m, name="habaki")

    # 3. Lame shinogi-zukuri continue par sweep() :
    #    dos épais (mune, -X), arêtes shinogi (±Y), tranchant rasoir (ha, +X),
    #    courbure sori lisse vers -X et pointe kissaki géométrique nette.
    blade_prof = np.array([
        [-0.0155,  0.0000],   # mune (dos)
        [-0.0135,  0.0036],   # flanc mune +Y
        [-0.0035,  0.0039],   # arête shinogi +Y
        [ 0.0155,  0.00035],  # tranchant ha (+X)
        [ 0.0155, -0.00035],
        [-0.0035, -0.0039],   # arête shinogi -Y
        [-0.0135, -0.0036],   # flanc mune -Y
    ]) * u

    n_st = 56
    ts = np.linspace(0.0, 1.0, n_st)
    z0_b, z1_b = 0.334 * u, float(length)
    # Le dos (mune) se courbe vers -X selon une parabole douce (sori authentique)
    xs_path = -float(sori) * (ts ** 1.75)
    zs_path = z0_b + (z1_b - z0_b) * ts
    blade_path = np.column_stack([xs_path, np.zeros_like(ts), zs_path])

    def _blade_taper(t: float):
        # Réduction progressive (fumbari -> motohaba -> sakihaba -> kissaki)
        w_t = 1.0 - 0.24 * (t ** 1.15)
        th_t = 1.0 - 0.34 * (t ** 1.05)
        if t > 0.915:
            # Kissaki : le tranchant remonte franchement vers la pointe
            u_k = (t - 0.915) / 0.085
            k_fac = max(0.035, (1.0 - u_k) ** 0.82)
            w_t *= k_fac
            th_t *= max(0.06, 1.0 - 0.92 * u_k)
        return (w_t, th_t)

    blade = mk.sweep(blade_prof, blade_path, scale=_blade_taper)
    b.add(blade, steel_m, name="blade")

    if textured:
        b.bake_pbr(
            overlays=[
                {"type": "wrap", "on": "tsuka", "diamond": True,
                 "under_color": same_color, "count": 9.5, "ribbon_width": 0.35},
                {"type": "brushed_metal", "on": "blade", "axis": "z",
                 "scale": 170.0, "amount": 0.11},
                {"type": "hamon", "on": "blade", "axis": "x",
                 "positive_edge": True, "edge_frac": 0.64, "freq": 62.0},
                {"type": "edge_wear", "on": ["blade", "habaki", "tsuba"],
                 "amount": 0.45, "scale": 20.0},
            ],
            texture_size=1024,
            normal_strength=1.8,
        )
    return b


@register("rocket", defaults={"height": 0.5, "radius": 0.06, "body_color": "#e8e6e1",
                              "accent_color": "#c0392b", "fins": 3},
          info=[{"name": "height", "type": "float"},
                {"name": "radius", "type": "float"},
                {"name": "body_color", "type": "color"},
                {"name": "accent_color", "type": "color"},
                {"name": "fins", "type": "int", "help": "3 ou 4 ailerons"}])
def build_rocket(height=0.5, radius=0.06, body_color="#e8e6e1",
                 accent_color="#c0392b", fins=3):
    b = mk.Builder("rocket", {})
    body_m = mk.mat.plastic(body_color, 0.3)
    accent_m = mk.mat.paint(accent_color, 0.3)
    dark_m = mk.mat.named_metal("steel", 0.45)

    nozzle_h = height * 0.14
    body_h = height * 0.60
    nose_h = height * 0.26
    body_z = nozzle_h * 0.55

    b.add(mk.frustum(radius * 0.55, radius * 0.85, nozzle_h), dark_m,
          name="nozzle", at=(0, 0, 0))
    b.add(mk.cylinder(radius, body_h, sections=48), body_m, name="body",
          at=(0, 0, body_z))
    b.add(mk.cone(radius, nose_h, sections=48), accent_m, name="nose",
          at=(0, 0, body_z + body_h))
    band = mk.cylinder(radius * 1.005, height * 0.03, sections=48)
    b.add(band, accent_m, name="band", at=(0, 0, body_z + body_h * 0.12))

    n = 3 if int(fins) < 4 else 4
    fin_pts = [(0, 0), (radius * 1.5, 0), (0, height * 0.26)]
    for i in range(n):
        ang = i * 360.0 / n
        fin = mk.extrude(fin_pts, 0.005)          # plan XY, épaisseur en Z
        mk.rot_x(fin, 90)                          # plan XZ (vertical)
        mk.rot_z(fin, ang)
        b.add(fin, accent_m, name=f"fin{i}",
              at=(0, 0, body_z + 0.004))
    ring = mk.torus(radius * 0.55, 0.005, major=32, minor=12, center=(0, 0, 0))
    mk.rot_x(ring, 90)
    b.add(ring, dark_m, name="porthole_ring",
          at=(0, -radius * 0.985, body_z + body_h * 0.55))
    window = mk.cylinder(radius * 0.42, 0.006, sections=32)
    mk.rot_x(window, 90)
    b.add(window, mk.mat.glass("#9fd8e8", 0.45, 0.05), name="porthole",
          at=(0, -radius * 0.99, body_z + body_h * 0.55))
    return b


@register("house", defaults={"width": 1.2, "depth": 0.9, "wall_height": 0.7,
                             "roof_height": 0.45, "wall_color": "#e6d9bd",
                             "roof_color": "#a0522d"},
          info=[{"name": "width", "type": "float"},
                {"name": "depth", "type": "float"},
                {"name": "wall_height", "type": "float"},
                {"name": "roof_height", "type": "float"},
                {"name": "wall_color", "type": "color"},
                {"name": "roof_color", "type": "color"}])
def build_house(width=1.2, depth=0.9, wall_height=0.7, roof_height=0.45,
                wall_color="#e8dec8", roof_color="#9e472a"):
    b = mk.Builder("house", {})
    b.def_joint("front_door", pivot=(-0.08, -depth / 2, 0.0), axis=(0, 0, 1))
    wall_m = mk.mat.paint(wall_color, 0.62)
    stone_m = mk.mat.paint("#7a7872", 0.78)
    roof_m = mk.mat.ceramic(roof_color, 0.34)
    trim_m = mk.mat.paint("#f4f2ec", 0.36)
    wood_m = mk.mat.wood("#5c3a1e", 0.46)
    glass_m = mk.mat.glass("#b8dce8", 0.24, 0.04)

    # Soubassement en pierre de taille + perron d'entrée à 2 marches
    plinth_h = 0.075
    b.add(mk.chamfer_box(width + 0.04, depth + 0.04, plinth_h, c=0.012),
          stone_m, name="foundation")
    b.add(mk.chamfer_box(0.30, 0.16, 0.042, c=0.006), stone_m,
          name="step_low", at=(0, -depth / 2 - 0.07, 0))
    b.add(mk.chamfer_box(0.26, 0.11, 0.075, c=0.006), stone_m,
          name="step_top", at=(0, -depth / 2 - 0.04, 0))

    # Murs creusés en VRAI CSG (ouvertures profondes de fenêtres et d'entrée + intérieur sombre)
    wall_shell = mk.box(width, depth, wall_height - plinth_h * 0.5)
    mk.place(wall_shell, 0, 0, plinth_h * 0.5)
    win_xs = (-width * 0.29, width * 0.29)
    cuts = []
    # Embrasure porte avant
    d_cut = mk.box(0.18, 0.09, 0.33)
    mk.place(d_cut, 0, -depth / 2 + 0.01, plinth_h)
    cuts.append(d_cut)
    # Fenêtres avant + arrière + pignons latéraux
    for wx in win_xs:
        for sy in (-1, 1):
            wc = mk.box(0.17, 0.09, 0.16)
            mk.place(wc, wx, sy * (depth / 2 - 0.01), 0.33)
            cuts.append(wc)
    for sx in (-1, 1):
        wc_s = mk.box(0.09, 0.16, 0.15)
        mk.place(wc_s, sx * (width / 2 - 0.01), 0.0, 0.35)
        cuts.append(wc_s)
    carved_walls = mk.difference(wall_shell, cuts)
    b.add(carved_walls, wall_m, name="walls")

    # Noyau intérieur sombre garantissant un fond réaliste derrière les vitres ET une union 100% étanche
    b.add(mk.box(width - 0.09, depth - 0.09, wall_height - 0.06),
          mk.mat.paint("#262428", 0.85), name="interior_core", at=(0, 0, plinth_h * 0.5))

    # Chaînages d'angle blancs
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.add(mk.box(0.045, 0.045, wall_height - plinth_h * 0.5), trim_m,
                  name=f"quoin_{sx}_{sy}",
                  at=(sx * (width / 2 - 0.018), sy * (depth / 2 - 0.018), plinth_h * 0.5))

    # Porte en bois panneautée articulée + poignée laiton + encadrement AJOURÉ (ne masque pas le bois !)
    df_outer = mk.box(0.224, 0.032, 0.352)
    mk.place(df_outer, 0, -depth / 2 - 0.004, plinth_h)
    df_hole = mk.box(0.168, 0.12, 0.322)
    mk.place(df_hole, 0, -depth / 2 - 0.02, plinth_h + 0.002)
    b.add(mk.difference(df_outer, [df_hole]), trim_m, name="door_frame")
    b.add(mk.rounded_box(0.168, 0.028, 0.322, r=0.006), wood_m, name="door",
          at=(0, -depth / 2 + 0.006, plinth_h + 0.002), group="front_door")
    b.add(mk.sphere(0.012, center=(0, 0, 0)), mk.mat.named_metal("brass", 0.22),
          name="knob", at=(0.056, -depth / 2 - 0.012, plinth_h + 0.15), group="front_door")

    # Fenêtres à cadres AJOURÉS + croisillons blancs + appuis pierre + vitres bleutées réfractives !
    glass_m = mk.mat.glass("#6fa8c4", 0.42, 0.05)
    for i, wx in enumerate(win_xs):
        for j, sy in enumerate((-1, 1)):
            tag = f"{i}_{j}"
            yw = sy * (depth / 2 - 0.002)
            wf_out = mk.box(0.208, 0.030, 0.198)
            mk.place(wf_out, wx, yw, 0.312)
            wf_in = mk.box(0.158, 0.12, 0.148)
            mk.place(wf_in, wx, yw, 0.337)
            b.add(mk.difference(wf_out, [wf_in]), trim_m, name=f"wframe_{tag}")
            b.add(mk.chamfer_box(0.232, 0.056, 0.024, c=0.004), stone_m,
                  name=f"sill_{tag}", at=(wx, sy * (depth / 2 + 0.014), 0.294))
            b.add(mk.box(0.160, 0.012, 0.150), glass_m, name=f"glass_{tag}",
                  at=(wx, sy * (depth / 2 - 0.020), 0.336))
            b.add(mk.box(0.013, 0.022, 0.154), trim_m, name=f"mullion_v_{tag}",
                  at=(wx, sy * (depth / 2 - 0.014), 0.334))
            b.add(mk.box(0.162, 0.022, 0.013), trim_m, name=f"mullion_h_{tag}",
                  at=(wx, sy * (depth / 2 - 0.014), 0.404))

    # Toiture à deux pans débordants + planches de rive blanches + faîtière + cheminée couronnée
    over = 0.085
    ridge = width + 2 * over
    roof = mk.extrude([(-depth / 2 - over, 0), (depth / 2 + over, 0),
                       (0, roof_height)], ridge)
    mk.rot_x(roof, 90)
    mk.rot_z(roof, 90)
    mk.place(roof, -ridge / 2, 0, 0)
    b.add(roof, roof_m, name="roof", at=(0, 0, wall_height - 0.015))
    b.add(mk.cylinder(0.026, ridge, sections=20), roof_m, name="ridge_cap",
          rot=(0, 90, 0), at=(-ridge / 2, 0, wall_height + roof_height - 0.02))
    for i, sy in enumerate((-1, 1)):
        b.add(mk.box(ridge, 0.022, 0.036), trim_m, name=f"eave_{i}",
              at=(0, sy * (depth / 2 + over - 0.008), wall_height - 0.032))

    cx, cy = width * 0.27, depth * 0.14
    cz = wall_height + roof_height * 0.42
    b.add(mk.box(0.115, 0.115, roof_height * 0.68), mk.mat.paint("#8a4629", 0.65),
          name="chimney", at=(cx, cy, cz))
    b.add(mk.chamfer_box(0.145, 0.145, 0.028, c=0.005), stone_m,
          name="chimney_cap", at=(cx, cy, cz + roof_height * 0.66))
    b.add(mk.tube(0.032, 0.019, 0.055, sections=20), roof_m,
          name="chimney_pot", at=(cx, cy, cz + roof_height * 0.68))
    return b


@register("tree", defaults={"kind": "pine", "height": 1.2},
          info=[{"name": "kind", "type": "choice", "choices": ["pine", "oak"]},
                {"name": "height", "type": "float", "help": "Hauteur totale"}])
def build_tree(kind="pine", height=1.2):
    b = mk.Builder("tree", {"kind": kind})
    H = float(height)
    trunk_m = mk.mat.wood("#5d3e24", 0.78)
    # Empattement racinaire naturel évasé à la base
    for i in range(5):
        ang = math.radians(i * 72.0 + 14.0)
        root_curve = np.array([
            [0.0, 0.0, 0.13 * H],
            [0.048 * H * math.cos(ang), 0.048 * H * math.sin(ang), 0.045 * H],
            [0.095 * H * math.cos(ang), 0.095 * H * math.sin(ang), 0.012 * H],
        ])
        b.add(mk.ground(mk.tube_sweep(root_curve, r=0.021 * H, sections=10, smooth_pts=14)),
              trunk_m, name=f"root_{i}")

    if kind == "pine":
        # Tronc élancé continu + 5 couronnes coniques organiques festonnées
        b.add(mk.frustum(0.052 * H, 0.018 * H, H * 0.86, sections=20), trunk_m, name="trunk")
        tiers = [
            (0.36, 0.08, 0.28, 0.15, "#234d20"),
            (0.30, 0.07, 0.26, 0.34, "#295c25"),
            (0.24, 0.06, 0.24, 0.52, "#316b2b"),
            (0.18, 0.045, 0.22, 0.68, "#397a32"),
            (0.115, 0.010, 0.20, 0.81, "#43893a"),
        ]
        for i, (rb, rt, fh, z0, col) in enumerate(tiers):
            leaf_m = mk.mat.paint(col, 0.74)
            # Cône festonné (lobes radiaux organiques au lieu d'un cône lisse géométrique !)
            n_pts = 48
            ths = np.linspace(0, 2 * math.pi, n_pts, endpoint=False)
            lobe = 1.0 + 0.10 * np.cos(7 * ths + i * 1.1) + 0.05 * np.sin(11 * ths)
            r0_ring = np.column_stack([rb * H * lobe * np.cos(ths),
                                       rb * H * lobe * np.sin(ths),
                                       np.zeros(n_pts)])
            r1_ring = np.column_stack([rb * 0.56 * H * lobe * np.cos(ths),
                                       rb * 0.56 * H * lobe * np.sin(ths),
                                       np.full(n_pts, fh * 0.52 * H)])
            r2_ring = np.column_stack([max(rt, 0.008) * H * np.cos(ths),
                                       max(rt, 0.008) * H * np.sin(ths),
                                       np.full(n_pts, fh * H)])
            crown = mk.loft([r0_ring, r1_ring, r2_ring], caps=True)
            b.add(crown, leaf_m, name=f"tier_{i}", at=(0, 0, z0 * H))
    else:
        # Chêne feuillu : tronc sinueux + vraies branches maîtresses cintrées `tube_sweep` + houppier multi-sphères
        trunk_curve = np.array([
            [0.0, 0.0, 0.0],
            [0.012 * H, -0.008 * H, 0.20 * H],
            [-0.010 * H, 0.012 * H, 0.42 * H],
            [0.005 * H, 0.0, 0.58 * H],
        ])
        b.add(mk.ground(mk.tube_sweep(trunk_curve, r=0.052 * H, sections=16, smooth_pts=20)),
              trunk_m, name="trunk")
        branches = [
            ([(0.0, 0.0, 0.40), (0.12, 0.05, 0.52), (0.21, 0.08, 0.63)], (0.22, 0.08, 0.67), 0.19, "#356828"),
            ([(0.0, 0.0, 0.42), (-0.13, -0.04, 0.54), (-0.20, -0.07, 0.65)], (-0.21, -0.08, 0.69), 0.18, "#3e762f"),
            ([(0.0, 0.0, 0.45), (0.04, -0.13, 0.57), (0.07, -0.20, 0.67)], (0.08, -0.20, 0.71), 0.17, "#468236"),
            ([(0.0, 0.0, 0.46), (-0.05, 0.13, 0.58), (-0.08, 0.19, 0.68)], (-0.08, 0.19, 0.72), 0.17, "#2f5e23"),
        ]
        for i, (bpts, cc, cr, col) in enumerate(branches):
            bp = np.asarray(bpts, dtype=float) * H
            b.add(mk.tube_sweep(bp, r=0.024 * H, sections=12, smooth_pts=16),
                  trunk_m, name=f"branch_{i}")
            b.add(mk.sphere(cr * H, center=(cc[0] * H, cc[1] * H, cc[2] * H), subdivisions=2),
                  mk.mat.paint(col, 0.76), name=f"canopy_{i}")
        b.add(mk.sphere(0.24 * H, center=(0.0, 0.0, 0.76 * H), subdivisions=2),
              mk.mat.paint("#427b33", 0.75), name="canopy_top")
    return b


@register("car", defaults={"length": 1.1, "width": 0.5, "color": "#c0392b",
                           "wheel_arches": True},
          info=[{"name": "length", "type": "float"},
                {"name": "width", "type": "float"},
                {"name": "color", "type": "color", "help": "Couleur de carrosserie"},
                {"name": "wheel_arches", "type": "bool",
                 "help": "Découper les passages de roues (CSG)"}])
def build_car(length=1.1, width=0.5, color="#b8251e", wheel_arches=True):
    from scipy.interpolate import PchipInterpolator

    b = mk.Builder("car", {})
    body_m = mk.mat.car_clearcoat(color, 0.12)
    glass_m = mk.mat.glass("#3a5266", 0.34, 0.04)
    trim_m = mk.mat.knobby_rubber("#1d1f23", 0.72)
    chrome_m = mk.mat.brushed_stainless("#dce1e8", 0.12)
    alloy_m = mk.mat.anodized_alu("#cfd5de", 0.22)

    L, W = float(length), float(width)
    body_z = 0.072 * (L / 1.1)
    wheel_r = 0.084 * (L / 1.1)
    wheel_x = L * 0.312

    b.def_joint("front_axle", pivot=(wheel_x, 0.0, wheel_r), axis=(0, 1, 0))
    b.def_joint("rear_axle", pivot=(-wheel_x, 0.0, wheel_r), axis=(0, 1, 0))

    # Caisse coupé GT fastback galbée PCHIP + habitacle vitré creusé en CSG !
    xs_top = np.linspace(-0.50, 0.50, 52)
    k_x = [-0.50, -0.47, -0.34, -0.18, 0.14, 0.30, 0.45, 0.50]
    k_z = [ 0.088, 0.148, 0.158, 0.160, 0.152, 0.140, 0.108, 0.058]
    zs_top = PchipInterpolator(k_x, k_z)(xs_top)
    lower_pts = ([(-0.50 * L, 0.008 * L), (0.50 * L, 0.008 * L)]
                 + [(float(x * L), float(z * L)) for x, z in zip(xs_top[::-1], zs_top[::-1])])
    lower = mk.extrude(lower_pts, W)
    mk.rot_x(lower, 90)
    mk.place(lower, 0, W / 2, 0)

    cab_pts = [(-0.34 * L, 0.140 * L), (0.22 * L, 0.132 * L),
               (0.06 * L, 0.278 * L), (-0.21 * L, 0.282 * L)]
    cabin = mk.extrude(cab_pts, W * 0.80)
    mk.rot_x(cabin, 90)
    mk.place(cabin, 0, W * 0.40, 0)
    body = mk.union([lower, cabin])

    cuts = []
    # Découpe traversante des vitres latérales dans le pavillon pour laisser voir l'habitacle !
    win_cut_pts = [(-0.29 * L, 0.158 * L), (0.17 * L, 0.150 * L),
                   (0.045 * L, 0.258 * L), (-0.195 * L, 0.262 * L)]
    win_cut = mk.extrude(win_cut_pts, W * 0.90)
    mk.rot_x(win_cut, 90)
    mk.place(win_cut, 0, W * 0.45, 0)
    cuts.append(win_cut)

    if wheel_arches:
        for sx in (-1, 1):
            well = mk.cylinder(wheel_r * 1.19, W + 0.06, sections=40)
            mk.rot_x(well, 90)
            mk.place(well, sx * wheel_x, W * 0.5 + 0.03, wheel_r - body_z)
            cuts.append(well)
    body = mk.difference(body, cuts)
    b.add(body, body_m, name="body", at=(0, 0, body_z))

    # Habitacle sombre intérieur (sièges + planche de bord) soudé au châssis
    b.add(mk.rounded_box(0.42 * L, W * 0.68, 0.13 * L, r=0.015 * L),
          trim_m, name="cockpit_interior", at=(-0.06 * L, 0, body_z + 0.11 * L))

    # Calandre avant noire + lame splitter + diffuseur arrière + doubles sorties d'échappement inox
    b.add(mk.rounded_box(0.036 * L, W * 0.96, 0.038 * L, r=0.010 * L),
          trim_m, name="splitter_front", at=(0.495 * L, 0, body_z + 0.006 * L))
    b.add(mk.chamfer_box(0.025 * L, W * 0.46, 0.046 * L, c=0.006 * L),
          trim_m, name="grille", at=(0.498 * L, 0, body_z + 0.042 * L))
    b.add(mk.rounded_box(0.040 * L, W * 0.96, 0.046 * L, r=0.010 * L),
          trim_m, name="diffuser_rear", at=(-0.495 * L, 0, body_z + 0.012 * L))
    b.add(mk.rounded_box(0.055 * L, W * 0.88, 0.014 * L, r=0.004 * L),
          trim_m, name="rear_lip_spoiler", at=(-0.472 * L, 0, body_z + 0.146 * L))
    for i, sy in enumerate((-1, 1)):
        tip = mk.tube(0.016 * L, 0.011 * L, 0.045 * L, sections=20)
        mk.rot_y(tip, -90)
        b.add(tip, chrome_m, name=f"exhaust_{i}",
              at=(-0.495 * L, sy * W * 0.24, body_z + 0.026 * L))
        # Rétroviseurs profilés sur tiges
        b.add(mk.rounded_box(0.042 * L, 0.048 * W, 0.026 * L, r=0.008 * L),
              body_m, name=f"mirror_{i}",
              at=(0.145 * L, sy * (W * 0.44), body_z + 0.152 * L))

    # Vraies roues : pneus sculptés + jantes alliage creuses à 5 branches + disques de frein !
    tw = 0.058 * (L / 1.1)
    for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (-1, 1), (1, 1)]):
        grp = "front_axle" if sx > 0 else "rear_axle"
        wy = sy * (W / 2 - tw * 0.42)
        tire = mk.tube(wheel_r, wheel_r * 0.58, tw, sections=40)
        mk.rot_x(tire, 90)
        mk.place(tire, 0, tw * 0.5, 0)
        b.add(tire, trim_m, name=f"tire{i}", at=(sx * wheel_x, wy, wheel_r), group=grp)

        rim = mk.tube(wheel_r * 0.60, wheel_r * 0.47, tw * 0.88, sections=32)
        mk.rot_x(rim, 90)
        mk.place(rim, 0, tw * 0.44, 0)
        b.add(rim, alloy_m, name=f"rim{i}", at=(sx * wheel_x, wy, wheel_r), group=grp)

        rotor = mk.cylinder(wheel_r * 0.42, tw * 0.25, sections=24)
        mk.rot_x(rotor, 90)
        mk.place(rotor, 0, tw * 0.125, 0)
        b.add(rotor, chrome_m, name=f"rotor{i}", at=(sx * wheel_x, wy, wheel_r), group=grp)

        hub = mk.cylinder(wheel_r * 0.16, tw * 0.90, sections=20)
        mk.rot_x(hub, 90)
        mk.place(hub, 0, tw * 0.45, 0)
        b.add(hub, alloy_m, name=f"hub{i}", at=(sx * wheel_x, wy, wheel_r), group=grp)
        for k in range(5):
            ang = k * 72.0 + 18.0
            sp = mk.box(wheel_r * 0.11, tw * 0.55, wheel_r * 0.52)
            mk.place(sp, 0, -tw * 0.275, 0)
            mk.rot_y(sp, ang)
            b.add(sp, alloy_m, name=f"spoke{i}_{k}",
                  at=(sx * wheel_x, wy, wheel_r), group=grp)

    # Vitrage réfractif complet (pare-brise, lunette et vitres latérales encastrées)
    ws = mk.rounded_box(0.175 * L, W * 0.75, 0.010 * L, r=0.004 * L)
    mk.rot_y(ws, 46.0)
    b.add(ws, glass_m, name="windshield", at=(0.145 * L, 0, body_z + 0.206 * L))
    rw = mk.rounded_box(0.165 * L, W * 0.75, 0.010 * L, r=0.004 * L)
    mk.rot_y(rw, -45.0)
    b.add(rw, glass_m, name="rear_window", at=(-0.272 * L, 0, body_z + 0.208 * L))
    # Vitres latérales trapézoïdales encastrées avec recouvrement franc de 3 mm dans le montant (zéro arête coplanaire !)
    cx_w = sum(p[0] for p in win_cut_pts) / 4.0
    cz_w = sum(p[1] for p in win_cut_pts) / 4.0
    win_pane_pts = [(cx_w + (p[0] - cx_w) * 1.04, cz_w + (p[1] - cz_w) * 1.04) for p in win_cut_pts]
    for i, sy in enumerate((-1, 1)):
        side_win = mk.extrude(win_pane_pts, 0.012)
        mk.rot_x(side_win, 90)
        mk.place(side_win, 0, sy * (W * 0.394) + 0.006, body_z)
        b.add(side_win, glass_m, name=f"side_window{i}")

    # Optiques LED avant + bandeau/feux LED arrière
    for i, sy in enumerate((-1, 1)):
        hl = mk.rounded_box(0.024 * L, W * 0.19, 0.024 * L, r=0.006 * L)
        b.add(hl, mk.mat.emissive("#fff6dd", 2.1), name=f"headlight{i}",
              at=(0.497 * L, sy * W * 0.32, body_z + 0.068 * L))
        tl = mk.rounded_box(0.020 * L, W * 0.24, 0.020 * L, r=0.005 * L)
        b.add(tl, mk.mat.emissive("#e62420", 1.6), name=f"taillight{i}",
              at=(-0.497 * L, sy * W * 0.31, body_z + 0.108 * L))
    return b


@register("motocross", defaults={"length": 2.2, "body_color": "#e8641b",
                                 "plate_color": "#e8641b", "seat_color": "#1a1a1a"},
          info=[{"name": "length", "type": "float",
                 "help": "Longueur totale en m (2.2 = 250cc taille réelle)"},
                {"name": "body_color", "type": "color",
                 "help": "Plastiques : shrouds, gardes-boue, pad de guidon"},
                {"name": "plate_color", "type": "color", "help": "Plaque avant"},
                {"name": "seat_color", "type": "color", "help": "Selle"}])
def build_motocross(length=2.2, body_color="#e8641b", plate_color="#f2f1ec",
                    seat_color="#1a1a1a"):
    """Moto de motocross (dirt bike) : roues à crampons, fourche inclinée,
    cadre twin-spar, moteur, échappement à chambrage, selle, shrouds,
    gardes-boue hauts, guidon avec barre transversale, bras oscillant,
    chaîne, disques de frein, amortisseur. Longueur ~2.2 m, selle ~0.97 m."""
    b = mk.Builder("motocross", {})
    u = length * 0.677                      # empattement (wheelbase)

    plastic_m = mk.mat.abs_injected(body_color, 0.26)
    plate_m = mk.mat.abs_injected(plate_color, 0.28)
    seat_m = mk.mat.fabric(seat_color, 0.86)
    rubber_m = mk.mat.knobby_rubber("#1c1d20", 0.88)
    rim_m = mk.mat.anodized_alu("#d8dce2", 0.20)
    steel_m = mk.mat.brushed_stainless("#cdd2d8", 0.16)
    dark_m = mk.mat.forged_iron("#585d64", 0.38)
    eng_m = mk.mat.anodized_alu("#b9bec6", 0.32)
    frame_m = mk.mat.anodized_alu("#cfd4dc", 0.24)

    rake = 26.0                             # chasse de la fourche (deg)
    # v2 : proportions calées sur photo KTM 450 profil (compare.py, IoU 0.55→0.80+)
    wr_f, wr_r = 0.262 * u, 0.252 * u       # rayons roues (crampons inclus)
    tw_f, tw_r = 0.058 * u, 0.075 * u       # largeurs pneus
    fx, fz = 0.5 * u, wr_f + 0.0125 * u     # centre roue avant (crampons au sol)
    rx, rz = -0.5 * u, wr_r + 0.0125 * u    # centre roue arrière

    # ---------------------------------------------------------------- helpers
    def cyl_y(r, h, sections=24):
        """Cylindre le long de Y, CENTRÉ à l'origine (rot_x(90) envoie +Z vers -Y)."""
        c = mk.cylinder(r, h, sections=sections)
        mk.rot_x(c, 90)
        mk.place(c, 0, h / 2, 0)
        return c
    def pipe(p0, p1, r, sections=24):
        """Cylindre du point (x,z) p0 au point p1 (dans le plan XZ), à y=0."""
        x0, z0 = p0
        x1, z1 = p1
        ln = math.hypot(x1 - x0, z1 - z0)
        seg = mk.cylinder(r, ln, sections=sections)
        mk.rot_y(seg, math.degrees(math.atan2(x1 - x0, z1 - z0)))
        return seg, (x0, z0)

    def arc_ring(cx, cz, r_out, r_in, a0, a1, n=14):
        """Polygone fermé (x, z) en couronne d'angles a0..a1 (degrés)."""
        outer = [(cx + r_out * math.cos(math.radians(a)),
                  cz + r_out * math.sin(math.radians(a)))
                 for a in np.linspace(a0, a1, n)]
        inner = [(cx + r_in * math.cos(math.radians(a)),
                  cz + r_in * math.sin(math.radians(a)))
                 for a in np.linspace(a1, a0, n)]
        return outer + inner

    def profile_solid(pts_xz, width):
        """Extrude un profil (x, z) — épaisseur `width` centrée en Y."""
        s = mk.extrude(pts_xz, width)
        mk.rot_x(s, 90)
        mk.place(s, 0, width / 2, 0)
        return s

    b.def_joint("front_wheel", pivot=(fx, 0.0, fz), axis=(0, 1, 0))
    b.def_joint("rear_wheel", pivot=(rx, 0.0, rz), axis=(0, 1, 0))
    b.def_joint("steering", pivot=(0.3286 * u, 0.0, 0.60 * u),
                axis=(-math.sin(math.radians(rake)), 0.0, math.cos(math.radians(rake))))

    # ---------------------------------------------------------------- roues rayonnées ajourées
    def wheel(cx, cz, wr, tw, tag):
        wgrp = "front_wheel" if tag == "f" else "rear_wheel"
        tread = mk.tube(wr, wr * 0.60, tw, sections=44)   # pneu creux réaliste
        mk.rot_x(tread, 90)
        mk.place(tread, 0, tw / 2, 0)
        b.add(tread, rubber_m, name=f"tire_{tag}", at=(cx, 0, cz), group=wgrp)
        for row, (y_off, phase) in enumerate(((-tw * 0.30, 0.0), (tw * 0.30, 8.0))):
            for i in range(22):
                ang = i * (360.0 / 22.0) + phase
                rad = math.radians(ang)
                knob = mk.chamfer_box(0.022 * u, tw * 0.36, 0.015 * u, c=0.003 * u)
                mk.place(knob, 0, 0, -0.0075 * u)
                mk.rot_y(knob, ang)
                b.add(knob, rubber_m, name=f"knob_{tag}_{row}_{i}",
                      at=(cx + (wr + 0.006 * u) * math.sin(rad), y_off,
                          cz + (wr + 0.006 * u) * math.cos(rad)), group=wgrp)
        # Vraie jante annulaire AJOURÉE (on voit à travers la roue comme sur une vraie moto !)
        rim_t = mk.tube(wr * 0.62, wr * 0.51, tw * 0.62, sections=40)
        mk.rot_x(rim_t, 90)
        mk.place(rim_t, 0, tw * 0.31, 0)
        b.add(rim_t, rim_m, name=f"rim_{tag}", at=(cx, 0, cz), group=wgrp)
        # Moyeu central CNC compact + 18 rayons croisés traversants
        b.add(cyl_y(wr * 0.145, tw * 0.86, sections=22), rim_m,
              name=f"hub_{tag}", at=(cx, 0, cz), group=wgrp)
        d = wr * 0.545
        for k in range(9):
            phi = math.radians(k * 20.0 + 7.0)
            y_slant = (0.14 * tw) * (1 if k % 2 == 0 else -1)
            p_a = np.array([cx - d * math.cos(phi), -y_slant, cz - d * math.sin(phi)])
            p_b = np.array([cx + d * math.cos(phi),  y_slant, cz + d * math.sin(phi)])
            sp = mk.tube_sweep(np.vstack([p_a, p_b]), r=0.0038 * u, sections=8, smooth_pts=4)
            b.add(sp, steel_m, name=f"spoke_{tag}_{k}", group=wgrp)

    wheel(fx, fz, wr_f, tw_f, "f")
    wheel(rx, rz, wr_r, tw_r, "r")

    # Disques de frein "Wave" festonnés et ajourés + couronne arrière dentée CNC !
    def wave_rotor(r_base, thick, lobes=8):
        ths = np.linspace(0, 2 * math.pi, 72, endpoint=False)
        rr = r_base * (1.0 + 0.065 * np.cos(lobes * ths))
        pts = [(float(r * math.cos(t)), float(r * math.sin(t))) for r, t in zip(rr, ths)]
        disc = mk.extrude(pts, thick)
        holes = [mk.cylinder(r_base * 0.09, thick * 3.0, sections=10)]
        for k in range(lobes):
            a = math.radians(k * (360.0 / lobes) + 18.0)
            hc = mk.cylinder(r_base * 0.075, thick * 3.0, sections=10)
            mk.place(hc, r_base * 0.66 * math.cos(a), r_base * 0.66 * math.sin(a), -thick)
            holes.append(hc)
        disc = mk.difference(disc, holes)
        mk.rot_x(disc, 90)
        mk.place(disc, 0, thick * 0.5, 0)
        return disc

    b.add(wave_rotor(wr_f * 0.38, 0.0055 * u, lobes=8), steel_m, name="disc_f",
          at=(fx, -(tw_f / 2 + 0.016 * u), fz), group="front_wheel")
    b.add(wave_rotor(wr_r * 0.36, 0.0055 * u, lobes=7), steel_m, name="disc_r",
          at=(rx, -(tw_r / 2 + 0.014 * u), rz), group="rear_wheel")
    b.add(wave_rotor(wr_r * 0.31, 0.011 * u, lobes=14), mk.mat.anodized_alu("#e8641b", 0.24),
          name="sprocket", at=(rx, 0.088 * u, rz), group="rear_wheel")

    # ---------------------------------------------------------------- fourche
    clamp_z = 0.79 * u
    clamp_x = fx - math.tan(math.radians(rake)) * (clamp_z - fz)
    top_x = clamp_x - math.tan(math.radians(rake)) * 0.012 * u   # dépasse la platine
    for i, sy in enumerate((-1, 1)):
        leg, (ax, az) = pipe((fx, fz), (top_x, clamp_z + 0.012 * u),
                             0.0145 * u, sections=16)
        b.add(leg, rim_m, name=f"fork_lower{i}", at=(ax, sy * 0.075 * u, az))
        boot, (bx, bz) = pipe((fx + math.tan(math.radians(rake)) * 0.015 * u,
                               fz + 0.015 * u),
                              (fx - math.tan(math.radians(rake)) * 0.30 * u,
                               fz + 0.30 * u), 0.021 * u, sections=16)
        b.add(boot, plastic_m, name=f"fork_boot{i}", at=(bx, sy * 0.075 * u, bz))
    head_tube, (hx, hz) = pipe((0.3286 * u, 0.60 * u),
                               (0.3286 * u - math.tan(math.radians(rake)) * 0.17 * u,
                                0.77 * u), 0.021 * u, sections=16)
    b.add(head_tube, frame_m, name="head_tube", at=(hx, 0, hz))
    for i, (cz2, cx2) in enumerate(((clamp_z, clamp_x), (0.60 * u, 0.3286 * u))):
        clamp = mk.chamfer_box(0.072 * u, 0.185 * u, 0.040 * u, c=0.008 * u)
        mk.place(clamp, 0, 0, -0.020 * u)          # centrage vertical (box posée)
        mk.rot_y(clamp, -rake)
        b.add(clamp, frame_m, name=f"clamp{i}", at=(cx2, 0, cz2))

    # Étrier de frein CNC + durite hydraulique souple reliant maître-cylindre -> étrier
    cal_f = mk.chamfer_box(0.052 * u, 0.036 * u, 0.068 * u, c=0.007 * u)
    b.add(cal_f, dark_m, name="caliper_f",
          at=(fx - wr_f * 0.28, -(tw_f / 2 + 0.018 * u), fz + wr_f * 0.14))
    hose = mk.cable([
        (clamp_x - 0.006 * u, -(0.14 * u), clamp_z + 0.125 * u),
        (fx - 0.16 * u, -(0.082 * u), 0.56 * u),
        (fx - wr_f * 0.28, -(tw_f / 2 + 0.018 * u), fz + wr_f * 0.18),
    ], r=0.0042 * u, sections=10, smooth_pts=28)
    b.add(hose, rubber_m, name="brake_hose_f")

    # ---------------------------------------------------------------- guidon cintré 3D + mousse ronde
    bar_z = clamp_z + 0.075 * u
    for i, sy in enumerate((-1, 1)):
        b.add(mk.chamfer_box(0.030 * u, 0.028 * u, 0.085 * u, c=0.005 * u),
              frame_m, name=f"riser{i}",
              at=(clamp_x - 0.004 * u, sy * 0.048 * u, clamp_z))
    hb_curve = np.array([
        [clamp_x - 0.028 * u, -0.265 * u, bar_z + 0.048 * u],
        [clamp_x - 0.014 * u, -0.135 * u, bar_z + 0.036 * u],
        [clamp_x - 0.004 * u, -0.065 * u, bar_z + 0.002 * u],
        [clamp_x - 0.004 * u,  0.065 * u, bar_z + 0.002 * u],
        [clamp_x - 0.014 * u,  0.135 * u, bar_z + 0.036 * u],
        [clamp_x - 0.028 * u,  0.265 * u, bar_z + 0.048 * u],
    ])
    b.add(mk.tube_sweep(hb_curve, r=0.011 * u, sections=14, smooth_pts=32),
          steel_m, name="handlebar")
    for i, sy in enumerate((-1, 1)):
        b.add(cyl_y(0.0155 * u, 0.115 * u, sections=16), rubber_m, name=f"grip{i}",
              at=(clamp_x - 0.022 * u, sy * 0.205 * u, bar_z + 0.043 * u))
    b.add(cyl_y(0.024 * u, 0.165 * u, sections=18), plastic_m, name="bar_pad",
          at=(clamp_x - 0.004 * u, 0, bar_z + 0.028 * u))
    b.add(cyl_y(0.0055 * u, 0.22 * u, sections=10), steel_m, name="crossbar",
          at=(clamp_x - 0.009 * u, 0, bar_z + 0.028 * u))

    # plaque numéro avant trapézoïdale inclinée selon la chasse
    plate = mk.rounded_box(0.014 * u, 0.165 * u, 0.225 * u, r=0.006 * u)
    mk.place(plate, 0, 0, -0.112 * u)
    mk.rot_y(plate, -rake)
    b.add(plate, plate_m, name="front_plate", at=(clamp_x + 0.042 * u, 0, clamp_z - 0.015 * u))

    # ---------------------------------------------------------------- cadre
    # twin-spar : ruban fin du tube de direction vers le pivot
    spar_pts = [(0.3466, 0.6368), (0.2934, 0.7032), (-0.1066, 0.3832),
                (-0.0534, 0.3168)]
    spar_pts = [(x * u, z * u) for x, z in spar_pts]
    for i, sy in enumerate((-1, 1)):
        spar = profile_solid(spar_pts, 0.045 * u)
        b.add(spar, frame_m, name=f"spar{i}", at=(0, sy * 0.09 * u, 0))
        down, (dx_, dz_) = pipe((0.30 * u, 0.60 * u), (0.19 * u, 0.345 * u),
                                0.024 * u, sections=14)
        b.add(down, frame_m, name=f"downtube{i}", at=(dx_, sy * 0.07 * u, dz_))
        rail = mk.box(0.65 * u, 0.022 * u, 0.035 * u)
        mk.rot_y(rail, -1.5)
        b.add(rail, frame_m, name=f"subframe{i}",
              at=(-0.225 * u, sy * 0.075 * u, 0.635 * u))

    # ---------------------------------------------------------------- moteur + amortisseur
    b.add(mk.rounded_box(0.24 * u, 0.145 * u, 0.19 * u, r=0.024 * u), eng_m,
          name="engine_block", at=(0.06 * u, 0, 0.30 * u))
    jug = mk.cylinder(0.052 * u, 0.14 * u, sections=20)
    mk.rot_y(jug, -18.0)
    b.add(jug, eng_m, name="cylinder_jug", at=(0.135 * u, 0, 0.45 * u))
    for k in range(5):
        fin = mk.chamfer_box(0.118 * u, 0.112 * u, 0.006 * u, c=0.002 * u)
        mk.rot_y(fin, -18.0)
        b.add(fin, eng_m, name=f"cyl_fin_{k}",
              at=((0.138 + 0.008 * k) * u, 0, (0.470 + 0.021 * k) * u))
    head = mk.rounded_box(0.115 * u, 0.115 * u, 0.048 * u, r=0.012 * u)
    mk.rot_y(head, -18.0)
    b.add(head, plastic_m, name="valve_cover", at=(0.165 * u, 0, 0.565 * u))
    b.add(cyl_y(0.062 * u, 0.030 * u, sections=24), eng_m, name="clutch_cover",
          at=(0.045 * u, 0.078 * u, 0.355 * u))
    b.add(cyl_y(0.054 * u, 0.030 * u, sections=24), eng_m, name="ignition_cover",
          at=(0.115 * u, -0.078 * u, 0.355 * u))
    # Vrai amortisseur arrière : tige chromée + ressort hélicoïdal 3D exact !
    damper, (shx, shz) = pipe((-0.10 * u, 0.58 * u), (-0.17 * u, 0.33 * u),
                              0.017 * u, sections=16)
    b.add(damper, steel_m, name="monoshock_shaft", at=(shx, 0, shz))
    spring_len = math.hypot(-0.07 * u, -0.25 * u) * 0.84
    spring = mk.helix_spring(r_coil=0.031 * u, r_wire=0.0068 * u,
                             pitch=spring_len / 7.0, turns=7.0, sections=10, pts_per_turn=18)
    mk.rot_y(spring, math.degrees(math.atan2(0.07, 0.25)) + 180.0)
    b.add(spring, mk.mat.car_clearcoat("#e03c20", 0.18), name="monoshock_spring",
          at=(-0.105 * u, 0, 0.56 * u))
    for i, sy in enumerate((-1, 1)):
        rad = mk.rounded_box(0.11 * u, 0.035 * u, 0.19 * u, r=0.008 * u)
        mk.rot_y(rad, -16.0)
        b.add(rad, frame_m, name=f"radiator{i}", at=(0.255 * u, sy * 0.088 * u, 0.47 * u))

    # Collecteur d'échappement cintré continu en inox poli (`tube_sweep` sans cassure !)
    header_curve = np.array([
        [0.145, -0.025, 0.455],
        [0.265, -0.068, 0.435],
        [0.312, -0.078, 0.355],
        [0.245, -0.075, 0.265],
        [0.045, -0.068, 0.242],
        [-0.185, -0.068, 0.305],
        [-0.335, -0.076, 0.432],
    ]) * u
    header = mk.tube_sweep(header_curve, r=0.022 * u, sections=18, smooth_pts=44)
    b.add(header, steel_m, name="exhaust_header")
    sil, (sx, sz) = pipe((-0.33 * u, 0.43 * u), (-0.74 * u, 0.52 * u), 0.041 * u,
                         sections=22)
    b.add(sil, rim_m, name="silencer", at=(sx, -0.078 * u, sz))
    tip = mk.tube_sweep(np.array([[-0.72 * u, -0.078 * u, 0.515 * u],
                                  [-0.785 * u, -0.078 * u, 0.528 * u]]),
                        r=0.024 * u, r_inner=0.017 * u, sections=20, smooth_pts=8)
    b.add(tip, dark_m, name="silencer_tip")

    # ---------------------------------------------------------------- boîte à air + plaques latérales
    # Boîte à air fine en retrait (laisse le moteur, le cadre twin-spar et le
    # ressort d'amortisseur ressortir en vrai relief 3D tout en soudant l'union).
    core_pts = [(0.38, 0.34), (0.40, 0.52), (0.34, 0.660), (0.10, 0.670),
                (-0.30, 0.660), (-0.44, 0.53), (-0.42, 0.41), (-0.32, 0.32),
                (-0.05, 0.28), (0.24, 0.275), (0.36, 0.29)]
    core = profile_solid([(x * u, z * u) for x, z in core_pts], 0.072 * u)
    b.add(core, mk.mat.plastic("#17181a", 0.55), name="frame_core")
    side_panel_pts = [(-0.06, 0.65), (-0.44, 0.65), (-0.50, 0.52),
                      (-0.32, 0.43), (-0.10, 0.50)]
    for i, sy in enumerate((-1, 1)):
        sp = profile_solid([(x * u, z * u) for x, z in side_panel_pts], 0.024 * u)
        b.add(sp, plate_m, name=f"side_plate{i}", at=(0, sy * 0.092 * u, 0))

    # ---------------------------------------------------------------- selle
    seat_pts = [(0.26, 0.670), (0.30, 0.725), (-0.52, 0.730), (-0.60, 0.675),
                (-0.50, 0.650), (0.16, 0.660)]
    seat = profile_solid([(x * u, z * u) for x, z in seat_pts], 0.105 * u)
    b.add(seat, seat_m, name="seat")

    # réservoir galbé + bouchon CNC + ouïes KTM bicolores
    b.add(mk.rounded_box(0.23 * u, 0.145 * u, 0.105 * u, r=0.030 * u), plastic_m,
          name="tank", at=(0.24 * u, 0, 0.615 * u))
    b.add(mk.cylinder(0.026 * u, 0.022 * u, sections=20), dark_m,
          name="gas_cap", at=(0.245 * u, 0, 0.712 * u))
    shroud_pts = [(0.40, 0.66), (0.28, 0.725), (0.05, 0.575), (0.10, 0.425),
                  (0.29, 0.46), (0.41, 0.565)]
    graphic_pts = [(0.38, 0.645), (0.27, 0.695), (0.11, 0.575), (0.28, 0.50)]
    for i, sy in enumerate((-1, 1)):
        shroud = profile_solid([(x * u, z * u) for x, z in shroud_pts], 0.026 * u)
        b.add(shroud, plastic_m, name=f"shroud{i}", at=(0, sy * 0.106 * u, 0))
        decal = profile_solid([(x * u, z * u) for x, z in graphic_pts], 0.006 * u)
        b.add(decal, plate_m, name=f"shroud_graphic{i}", at=(0, sy * 0.118 * u, 0))

    # gardes-boue (couronnes d'arc extrudées)
    ffender = profile_solid(arc_ring(fx, fz, wr_f + 0.036 * u, wr_f + 0.014 * u,
                                     42.0, 98.0), 0.065 * u)
    b.add(ffender, plastic_m, name="front_fender")
    rfender = profile_solid([(-0.28 * u, 0.34 * u), (-0.42 * u, 0.46 * u),
                             (-0.56 * u, 0.58 * u), (-0.68 * u, 0.70 * u),
                             (-0.74 * u, 0.675 * u), (-0.62 * u, 0.545 * u),
                             (-0.48 * u, 0.42 * u), (-0.36 * u, 0.30 * u),
                             (-0.25 * u, 0.28 * u)], 0.10 * u)
    b.add(rfender, plastic_m, name="rear_fender")
    for i, sy in enumerate((-1, 1)):
        wedge = mk.box(0.10 * u, 0.045 * u, 0.04 * u)
        mk.place(wedge, 0, 0, -0.02 * u)             # centrage vertical
        mk.rot_y(wedge, -23.0)
        b.add(wedge, plastic_m, name=f"fender_mount{i}",
              at=(0.40 * u, sy * 0.065 * u, 0.558 * u))   # chevauche la fourche franchement

    # ---------------------------------------------------------------- oscillant + chaîne
    for i, sy in enumerate((-1, 1)):
        arm = mk.box(0.44 * u, 0.026 * u, 0.085 * u)
        mk.rot_y(arm, -12.7)
        b.add(arm, frame_m, name=f"swingarm{i}",
              at=(-0.29 * u, sy * 0.065 * u, 0.288 * u))
    chain_m = dark_m
    top_run = mk.box(0.53 * u, 0.010 * u, 0.016 * u)
    mk.rot_y(top_run, -2.6)
    b.add(top_run, chain_m, name="chain_top", at=(-0.24 * u, 0.088 * u, 0.320 * u))
    bot_run = mk.box(0.53 * u, 0.010 * u, 0.016 * u)
    mk.rot_y(bot_run, -6.1)
    b.add(bot_run, chain_m, name="chain_bottom", at=(-0.24 * u, 0.088 * u, 0.200 * u))

    # ---------------------------------------------------------------- cale-pieds
    for i, sy in enumerate((-1, 1)):
        b.add(mk.box(0.02 * u, 0.045 * u, 0.02 * u), steel_m, name=f"peg_mount{i}",
              at=(0.0, sy * 0.075 * u, 0.28 * u))
        b.add(mk.box(0.055 * u, 0.030 * u, 0.009 * u), steel_m, name=f"peg{i}",
              at=(0.0, sy * 0.098 * u, 0.28 * u))

    # ---------------------------------------------------------------- amortisseur
    shock, (sx, sz) = pipe((-0.28 * u, 0.305 * u), (-0.43 * u, 0.55 * u),
                           0.017 * u, sections=14)
    b.add(shock, rim_m, name="shock_body", at=(sx, 0, sz))
    shaft, (sx2, sz2) = pipe((-0.355 * u, 0.428 * u), (-0.43 * u, 0.55 * u),
                             0.009 * u, sections=10)
    b.add(shaft, steel_m, name="shock_shaft", at=(sx2, 0, sz2))
    return b
