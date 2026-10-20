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
    blade_m = mk.mat.named_metal(blade_color, 0.22)
    guard_m = mk.mat.named_metal(guard_color, 0.35)
    grip_m = mk.mat.rubber("#3b2a1c", 0.75)

    grip_h = length * 0.14
    guard_z = grip_h + 0.008
    blade_h = length - grip_h - length * 0.10

    grip = mk.capsule(0.011, grip_h * 0.8)
    b.add(grip, grip_m, name="grip", at=(0, 0, grip_h * 0.10))
    pommel = mk.sphere(0.016, center=(0, 0, 0.014))
    b.add(pommel, guard_m, name="pommel")

    guard = mk.box(0.115, 0.020, 0.016)
    b.add(guard, guard_m, name="guard", at=(0, 0, guard_z))
    blade = mk.box(0.032, 0.0062, blade_h * 0.92)
    b.add(blade, blade_m, name="blade", at=(0, 0, guard_z + 0.008))
    tip = mk.cone(0.016, length * 0.10)
    mk.scale(tip, (1.0, 0.40, 1.0))
    b.add(tip, blade_m, name="tip", at=(0, 0, guard_z + 0.008 + blade_h * 0.92))
    fuller = mk.box(0.004, 0.0075, blade_h * 0.6)
    b.add(fuller, guard_m, name="fuller", at=(0, 0, guard_z + blade_h * 0.35))
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
                wall_color="#e6d9bd", roof_color="#a0522d"):
    b = mk.Builder("house", {})
    wall_m = mk.mat.paint(wall_color, 0.55)
    roof_m = mk.mat.paint(roof_color, 0.5)
    wood_m = mk.mat.wood("#5b3a1e", 0.5)
    glass_m = mk.mat.glass("#a8ccd8", 0.4, 0.08)

    walls = mk.box(width, depth, wall_height)
    b.add(walls, wall_m, name="walls")
    over = 0.07
    ridge = width + 2 * over
    # extrudé : x=profondeur du pignon, y=hauteur, z=longueur de crête
    roof = mk.extrude([(-depth / 2 - over, 0), (depth / 2 + over, 0),
                       (0, roof_height)], ridge)
    mk.rot_x(roof, 90)                            # (x,y,z) -> (x,-z,y)
    mk.rot_z(roof, 90)                            # -> (crête X, profondeur Y, hauteur Z)
    mk.place(roof, -ridge / 2, 0, 0)              # centre la crête (extrusion de 0 à ridge)
    b.add(roof, roof_m, name="roof", at=(0, 0, wall_height))

    door = mk.box(0.16, 0.025, 0.30)
    b.add(door, wood_m, name="door", at=(0, -depth / 2 - 0.004, 0))
    knob = mk.sphere(0.010, center=(0, 0, 0))
    b.add(knob, mk.mat.named_metal("brass", 0.3), name="knob",
          at=(0.055, -depth / 2 - 0.02, 0.15))

    for i, wx in enumerate((-width * 0.28, width * 0.28)):
        frame = mk.box(0.20, 0.02, 0.18)
        b.add(frame, wall_m, name=f"win_frame{i}", at=(wx, -depth / 2 - 0.004, 0.34))
        win = mk.box(0.15, 0.022, 0.13)
        b.add(win, glass_m, name=f"window{i}", at=(wx, -depth / 2 - 0.006, 0.34))

    chimney = mk.box(0.09, 0.09, roof_height * 0.62)
    b.add(chimney, mk.mat.paint("#8d4f2a", 0.6), name="chimney",
          at=(width * 0.26, depth * 0.12, wall_height + roof_height * 0.52))
    return b


@register("tree", defaults={"kind": "pine", "height": 1.2},
          info=[{"name": "kind", "type": "choice", "choices": ["pine", "oak"]},
                {"name": "height", "type": "float", "help": "Hauteur totale"}])
def build_tree(kind="pine", height=1.2):
    b = mk.Builder("tree", {"kind": kind})
    trunk_m = mk.mat.wood("#6b4a2c", 0.65)
    if kind == "pine":
        trunk_h = height * 0.22
        b.add(mk.frustum(0.055, 0.04, trunk_h), trunk_m, name="trunk")
        tiers = [(0.42, 0.30, 0.46, 0.16, "#2d5a27"),
                 (0.33, 0.22, 0.40, 0.52, "#356b2d"),
                 (0.24, 0.10, 0.34, 0.84, "#3f7d34")]
        for i, (rb, rt, frac, z0, col) in enumerate(tiers):
            th = height * frac
            b.add(mk.frustum(rb * height, rt * height, th),
                  mk.mat.paint(col, 0.7), name=f"tier{i}", at=(0, 0, height * z0))
        b.add(mk.cone(0.09 * height, height * 0.12),
              mk.mat.paint("#3f7d34", 0.7), name="tip",
              at=(0, 0, height * (0.84 + 0.34)))
    else:
        trunk_h = height * 0.36
        b.add(mk.frustum(0.075, 0.05, trunk_h), trunk_m, name="trunk")
        canopy = [(0.30, (0.0, 0.0, 0.60), "#3a6b2a"),
                  (0.24, (0.17, 0.06, 0.74), "#4a7d34"),
                  (0.21, (-0.16, -0.07, 0.72), "#417332")]
        for i, (r, c, col) in enumerate(canopy):
            b.add(mk.sphere(r * height, center=(c[0] * height, c[1] * height,
                                                c[2] * height)),
                  mk.mat.paint(col, 0.8), name=f"blob{i}")
    return b


@register("car", defaults={"length": 1.1, "width": 0.5, "color": "#c0392b",
                           "wheel_arches": True},
          info=[{"name": "length", "type": "float"},
                {"name": "width", "type": "float"},
                {"name": "color", "type": "color", "help": "Couleur de carrosserie"},
                {"name": "wheel_arches", "type": "bool",
                 "help": "Découper les passages de roues (CSG)"}])
def build_car(length=1.1, width=0.5, color="#c0392b", wheel_arches=True):
    b = mk.Builder("car", {})
    body_m = mk.mat.paint(color, 0.22)
    glass_m = mk.mat.glass("#aacdd8", 0.45, 0.06)

    L, W = length, width
    profile = [(-L * 0.50, 0.00), (L * 0.50, 0.00), (L * 0.50, 0.115),
               (L * 0.36, 0.13), (L * 0.17, 0.305), (-L * 0.14, 0.32),
               (-L * 0.30, 0.15), (-L * 0.50, 0.135)]
    body = mk.extrude(profile, W)                 # profil XY (x=long, y=haut), épaisseur Z
    mk.rot_x(body, 90)                            # y→Z (hauteur vers le haut), Z→-y
    mk.place(body, 0, W / 2, 0)                   # recentre la largeur
    body_z = 0.10
    wheel_r = 0.075

    if wheel_arches:
        wells = []
        for sx in (-1, 1):
            well = mk.cylinder(wheel_r * 1.18, W + 0.02, sections=32)
            mk.rot_x(well, 90)
            mk.place(well, sx * L * 0.31, 0, body_z + wheel_r)
            wells.append(well)
        body = mk.difference(body, wells)
    b.add(body, body_m, name="body", at=(0, 0, body_z))

    wheel_x = L * 0.31
    tire_m = mk.mat.rubber("#1f1f1f", 0.85)
    hub_m = mk.mat.named_metal("aluminum", 0.35)
    for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (-1, 1), (1, 1)]):
        tire = mk.cylinder(wheel_r, 0.042, sections=36)
        mk.rot_x(tire, 90)
        b.add(tire, tire_m, name=f"tire{i}",
              at=(sx * wheel_x, sy * (W / 2 - 0.012), wheel_r))
        hub = mk.cylinder(wheel_r * 0.45, 0.046, sections=24)
        mk.rot_x(hub, 90)
        b.add(hub, hub_m, name=f"hub{i}",
              at=(sx * wheel_x, sy * (W / 2 - 0.012), wheel_r))

    for i, sy in enumerate((-1, 1)):
        side_win = mk.box(L * 0.26, 0.008, 0.085)
        b.add(side_win, glass_m, name=f"side_window{i}",
              at=(-L * 0.005, sy * (W / 2 - 0.001), body_z + 0.235))
    headlight = mk.box(0.012, W * 0.7, 0.035)
    b.add(headlight, mk.mat.emissive("#fff2c0", 1.6), name="headlights",
          at=(L * 0.498, 0, body_z + 0.095))
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

    plastic_m = mk.mat.plastic(body_color, 0.32)
    plate_m = mk.mat.plastic(plate_color, 0.30)
    seat_m = mk.mat.fabric(seat_color, 0.9)
    rubber_m = mk.mat.rubber("#1c1c1c", 0.92)
    rim_m = mk.mat.named_metal("aluminum", 0.35)
    steel_m = mk.mat.named_metal("steel", 0.40)
    dark_m = mk.mat.named_metal("steel", 0.60)
    eng_m = mk.mat.named_metal("aluminum", 0.50)
    frame_m = mk.mat.named_metal("aluminum", 0.45)

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

    # ---------------------------------------------------------------- roues
    def wheel(cx, cz, wr, tw, tag):
        tread = mk.tube(wr, wr * 0.58, tw, sections=40)   # couronne, jante visible
        mk.rot_x(tread, 90)
        mk.place(tread, 0, tw / 2, 0)
        b.add(tread, rubber_m, name=f"tire_{tag}", at=(cx, 0, cz))
        for row, (y_off, phase) in enumerate(((-tw * 0.30, 0.0), (tw * 0.30, 9.0))):
            for i in range(20):
                ang = i * 18.0 + phase
                rad = math.radians(ang)
                knob = mk.box(0.021 * u, tw * 0.36, 0.013 * u)
                mk.place(knob, 0, 0, -0.0065 * u)   # centrage radial (box posée)
                mk.rot_y(knob, ang)
                b.add(knob, rubber_m, name=f"knob_{tag}_{row}_{i}",
                      at=(cx + (wr + 0.006 * u) * math.sin(rad), y_off,
                          cz + (wr + 0.006 * u) * math.cos(rad)))
        rim_t = mk.tube(wr * 0.60, wr * 0.14, tw * 0.5, sections=28)  # jante creuse
        mk.rot_x(rim_t, 90)
        mk.place(rim_t, 0, tw * 0.25, 0)
        b.add(rim_t, rim_m, name=f"rim_{tag}", at=(cx, 0, cz))
        b.add(cyl_y(wr * 0.13, tw * 0.9, sections=18), rim_m,
              name=f"hub_{tag}", at=(cx, 0, cz))
        d = wr * 0.60 * 0.97
        for k in range(5):
            phi = math.radians(k * 36.0 + 10.0)
            seg, (sx, sz) = pipe((cx - d * math.cos(phi), cz - d * math.sin(phi)),
                                 (cx + d * math.cos(phi), cz + d * math.sin(phi)),
                                 0.003 * u, sections=8)
            b.add(seg, steel_m, name=f"spoke_{tag}_{k}", at=(sx, 0, sz))

    wheel(fx, fz, wr_f, tw_f, "f")
    wheel(rx, rz, wr_r, tw_r, "r")

    # disques de frein + pignon
    b.add(cyl_y(wr_f * 0.36, 0.006 * u, sections=32), steel_m, name="disc_f",
          at=(fx, -(tw_f / 2 + 0.016 * u), fz))
    b.add(cyl_y(wr_r * 0.36, 0.006 * u, sections=32), steel_m, name="disc_r",
          at=(rx, -(tw_r / 2 + 0.014 * u), rz))
    b.add(cyl_y(wr_r * 0.30, 0.014 * u, sections=28), dark_m, name="sprocket",
          at=(rx, 0.088 * u, rz))

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
        clamp = mk.box(0.07 * u, 0.185 * u, 0.040 * u)
        mk.place(clamp, 0, 0, -0.020 * u)          # centrage vertical (box posée)
        mk.rot_y(clamp, -rake)
        b.add(clamp, frame_m, name=f"clamp{i}", at=(cx2, 0, cz2))

    # ---------------------------------------------------------------- guidon
    bar_z = clamp_z + 0.130 * u
    for i, sy in enumerate((-1, 1)):
        b.add(mk.box(0.032 * u, 0.10 * u, 0.15 * u), frame_m, name=f"riser{i}",
              at=(clamp_x - 0.004 * u, sy * 0.045 * u, clamp_z))
    b.add(cyl_y(0.011 * u, 0.52 * u, sections=14), steel_m, name="handlebar",
          at=(clamp_x - 0.006 * u, 0, bar_z))
    for i, sy in enumerate((-1, 1)):
        b.add(cyl_y(0.015 * u, 0.115 * u, sections=14), rubber_m, name=f"grip{i}",
              at=(clamp_x - 0.006 * u, sy * 0.2025 * u, bar_z))
    b.add(mk.box(0.20 * u, 0.052 * u, 0.042 * u), plastic_m, name="bar_pad",
          at=(clamp_x - 0.006 * u, 0, bar_z - 0.021 * u))
    b.add(cyl_y(0.006 * u, 0.18 * u, sections=10), steel_m, name="crossbar",
          at=(clamp_x - 0.006 * u, 0, bar_z + 0.002 * u))

    # plaque avant (devant la fourche, inclinée selon la chasse)
    plate = mk.box(0.012 * u, 0.14 * u, 0.28 * u)
    mk.place(plate, 0, 0, -0.14 * u)                # centrage vertical
    mk.rot_y(plate, -25.0)
    b.add(plate, plate_m, name="front_plate", at=(0.42 * u, 0, 0.63 * u))

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

    # ---------------------------------------------------------------- moteur
    b.add(mk.box(0.24 * u, 0.14 * u, 0.20 * u), eng_m, name="engine_block",
          at=(0.06 * u, 0, 0.38 * u))
    jug = mk.cylinder(0.037 * u, 0.11 * u, sections=20)
    mk.rot_y(jug, -25.0)
    b.add(jug, eng_m, name="cylinder_jug", at=(0.115 * u, 0, 0.50 * u))
    b.add(cyl_y(0.052 * u, 0.018 * u, sections=24), eng_m, name="clutch_cover",
          at=(0.045 * u, 0.068 * u, 0.40 * u))
    b.add(cyl_y(0.045 * u, 0.018 * u, sections=24), eng_m, name="ignition_cover",
          at=(0.115 * u, -0.068 * u, 0.40 * u))

    # ---------------------------------------------------------------- échappement
    segs = [(((0.145, 0.415), (0.315, 0.30)), 0.024, -0.045, "pipe_head"),
            (((0.315, 0.30), (0.06, 0.235)), 0.040, -0.045, "chamber_belly"),
            (((0.06, 0.235), (-0.21, 0.30)), 0.030, -0.045, "chamber_tail"),
            (((-0.21, 0.30), (-0.33, 0.43)), 0.020, -0.060, "stinger")]
    for (p0, p1), r, ey, nm in segs:
        seg, (sx, sz) = pipe((p0[0] * u, p0[1] * u), (p1[0] * u, p1[1] * u), r * u)
        b.add(seg, steel_m, name=nm, at=(sx, ey * u, sz))
    sil, (sx, sz) = pipe((-0.33 * u, 0.43 * u), (-0.74 * u, 0.52 * u), 0.040 * u,
                         sections=20)
    b.add(sil, rim_m, name="silencer", at=(sx, -0.072 * u, sz))

    # ---------------------------------------------------------------- noyau carcasse
    # Pièce pleine qui remplit le volume selle→moteur (v2 : supprime les trous
    # de silhouette — cf. compare.py ; la vraie moto est pleine vue de profil).
    core_pts = [(0.44, 0.32), (0.45, 0.50), (0.34, 0.660), (0.10, 0.670),
                (-0.30, 0.660), (-0.46, 0.52), (-0.46, 0.40), (-0.36, 0.31),
                (-0.05, 0.27), (0.24, 0.265), (0.40, 0.27)]
    core = profile_solid([(x * u, z * u) for x, z in core_pts], 0.12 * u)
    b.add(core, mk.mat.plastic("#17181a", 0.55), name="frame_core")

    # ---------------------------------------------------------------- selle
    seat_pts = [(0.26, 0.670), (0.30, 0.725), (-0.52, 0.730), (-0.60, 0.675),
                (-0.50, 0.650), (0.16, 0.660)]
    seat = profile_solid([(x * u, z * u) for x, z in seat_pts], 0.105 * u)
    b.add(seat, seat_m, name="seat")

    # réservoir + shrouds (v2 : montés haut, look KTM anguleux)
    b.add(mk.box(0.24 * u, 0.15 * u, 0.10 * u), plastic_m, name="tank",
          at=(0.33 * u, 0, 0.59 * u))
    shroud_pts = [(0.42, 0.67), (0.30, 0.73), (0.06, 0.57), (0.10, 0.42),
                  (0.30, 0.46), (0.42, 0.57)]
    for i, sy in enumerate((-1, 1)):
        shroud = profile_solid([(x * u, z * u) for x, z in shroud_pts], 0.032 * u)
        b.add(shroud, plastic_m, name=f"shroud{i}", at=(0, sy * 0.115 * u, 0))

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
