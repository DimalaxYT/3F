"""Recettes mobilier : chair, table, stool, bookshelf, lamp."""
from __future__ import annotations
import numpy as np
from .registry import register
import meshkit as mk

@register("chair", defaults={"style": "scandinavian", "wood_color": "#b08850",
                             "seat_color": "#c8a878", "scale": 1.0},
          info=[{"name": "style", "type": "choice", "choices": ["scandinavian", "classic"],
                 "help": "Silhouette du dossier et forme des pieds"},
                {"name": "wood_color", "type": "color", "help": "Couleur du bois (structure)"},
                {"name": "seat_color", "type": "color", "help": "Couleur de l'assise"},
                {"name": "scale", "type": "float", "help": "Facteur d'échelle global"}])
def build_chair(style="scandinavian", wood_color="#b08850", seat_color="#c8a878", scale=1.0):
    b = mk.Builder("chair", {"style": style})
    wood = mk.mat.wood(wood_color)
    seat_m = mk.mat.fabric(seat_color)
    if style == "scandinavian":
        seat = mk.box(0.42, 0.42, 0.045)
        b.add(seat, seat_m, name="seat", at=(0, 0, 0.44))
        for i, (sx, sy) in enumerate([(-0.17, -0.17), (0.17, -0.17),
                                      (-0.17, 0.17), (0.17, 0.17)]):
            leg = mk.frustum(0.024, 0.016, 0.44)
            if sy > 0:  # pieds arrière prolongés = montants du dossier
                leg = mk.frustum(0.024, 0.014, 0.88)
                leg = mk.rot_x(leg, -6.0)
                b.add(leg, wood, name=f"post{i}", at=(sx, sy, 0.02))
            else:
                b.add(leg, wood, name=f"leg{i}", at=(sx, sy, 0))
        for k, z in enumerate((0.62, 0.74, 0.86)):
            slat = mk.box(0.34, 0.025, 0.06)
            b.add(slat, wood, name=f"slat{k}", at=(0, 0.175, z))
    else:  # classic
        seat = mk.box(0.44, 0.44, 0.05)
        b.add(seat, seat_m, name="seat", at=(0, 0, 0.44))
        for i, (sx, sy) in enumerate([(-0.18, -0.18), (0.18, -0.18),
                                      (-0.18, 0.18), (0.18, 0.18)]):
            leg = mk.box(0.045, 0.045, 0.88 if sy > 0 else 0.44)
            b.add(leg, wood, name=f"leg{i}", at=(sx, sy, 0))
        panel = mk.box(0.40, 0.03, 0.32)
        b.add(panel, wood, name="back_panel", at=(0, 0.18, 0.68))
        rail = mk.box(0.40, 0.045, 0.05)
        b.add(rail, wood, name="back_rail", at=(0, 0.18, 0.86))
    if scale != 1.0:
        for m, mm, name in list(b._parts):
            mk.scale(m, scale)
    return b


@register("table", defaults={"style": "rect", "width": 1.2, "height": 0.75,
                             "wood_color": "#9a6b3f"},
          info=[{"name": "style", "type": "choice", "choices": ["rect", "round"]},
                {"name": "width", "type": "float", "help": "Largeur (ou diamètre) en m"},
                {"name": "height", "type": "float", "help": "Hauteur du plateau"},
                {"name": "wood_color", "type": "color"}])
def build_table(style="rect", width=1.2, height=0.75, wood_color="#9a6b3f"):
    b = mk.Builder("table", {"style": style})
    wood = mk.mat.wood(wood_color)
    if style == "round":
        top = mk.cylinder(width / 2, 0.04, sections=48)
        b.add(top, wood, name="top", at=(0, 0, height - 0.04))
        ped = mk.frustum(0.10, 0.055, height - 0.10)
        b.add(ped, wood, name="pedestal", at=(0, 0, 0.05))
        foot = mk.frustum(0.26, 0.20, 0.05)
        b.add(foot, wood, name="foot")
    else:
        top = mk.box(width, width * 0.62, 0.04)
        b.add(top, wood, name="top", at=(0, 0, height - 0.04))
        for i, (sx, sy) in enumerate([(-1, -1), (1, -1), (-1, 1), (1, 1)]):
            leg = mk.box(0.055, 0.055, height - 0.04)
            b.add(leg, wood, name=f"leg{i}",
                  at=(sx * (width / 2 - 0.10), sy * (width * 0.62 / 2 - 0.10), 0))
    return b


@register("stool", defaults={"height": 0.55, "radius": 0.17, "wood_color": "#a97c50"},
          info=[{"name": "height", "type": "float"},
                {"name": "radius", "type": "float", "help": "Rayon de l'assise"},
                {"name": "wood_color", "type": "color"}])
def build_stool(height=0.55, radius=0.17, wood_color="#a97c50"):
    b = mk.Builder("stool", {})
    wood = mk.mat.wood(wood_color)
    seat = mk.cylinder(radius, 0.04, sections=40)
    b.add(seat, wood, name="seat", at=(0, 0, height - 0.04))
    leg_h = height - 0.02
    for i in range(3):
        ang = np.deg2rad(90 + i * 120)
        leg = mk.frustum(0.020, 0.013, leg_h)
        mk.rot_x(leg, 7.0)
        mk.rot_z(leg, -np.rad2deg(ang))
        b.add(leg, wood, name=f"leg{i}",
              at=(np.cos(ang) * radius * 0.72, np.sin(ang) * radius * 0.72, 0))
    ring = mk.torus(radius * 0.62, 0.011, center=(0, 0, leg_h * 0.42))
    b.add(ring, wood, name="stretcher")
    return b


@register("bookshelf", defaults={"width": 0.9, "height": 1.8, "depth": 0.32,
                                 "shelves": 5, "wood_color": "#8b5e34"},
          info=[{"name": "width", "type": "float"},
                {"name": "height", "type": "float"},
                {"name": "depth", "type": "float"},
                {"name": "shelves", "type": "int", "help": "Nombre total de tablettes"},
                {"name": "wood_color", "type": "color"}])
def build_bookshelf(width=0.9, height=1.8, depth=0.32, shelves=5, wood_color="#8b5e34"):
    b = mk.Builder("bookshelf", {"shelves": shelves})
    wood = mk.mat.wood(wood_color)
    t = 0.025
    b.add(mk.box(t, depth, height), wood, name="side_left", at=(-width / 2 + t / 2, 0, 0))
    b.add(mk.box(t, depth, height), wood, name="side_right", at=(width / 2 - t / 2, 0, 0))
    b.add(mk.box(width, 0.015, height), wood, name="back", at=(0, depth / 2 - 0.008, 0))
    n = max(2, int(shelves))
    for i in range(n):
        z = t / 2 + i * (height - t) / (n - 1)
        b.add(mk.box(width - 2 * t, depth - 0.02, t), wood, name=f"shelf{i}",
              at=(0, -0.01, z))
    return b


@register("lamp", defaults={"style": "floor", "height": 1.5, "shade_color": "#e8dfc8"},
          info=[{"name": "style", "type": "choice", "choices": ["floor", "desk"]},
                {"name": "height", "type": "float", "help": "Hauteur totale"},
                {"name": "shade_color", "type": "color", "help": "Couleur de l'abat-jour"}])
def build_lamp(style="floor", height=1.5, shade_color="#e8dfc8"):
    b = mk.Builder("lamp", {"style": style})
    metal = mk.mat.named_metal("brass", 0.35)
    shade_h = 0.24 if style == "floor" else 0.14
    shade_m = mk.Material("shade", shade_color, roughness=0.8,
                          emissive=mk.hex_rgb(shade_color) * 0.30)
    if style == "floor":
        b.add(mk.cylinder(0.16, 0.025, sections=40), mk.mat.named_metal("steel", 0.5),
              name="base")
        pole_h = height - shade_h - 0.025
        b.add(mk.cylinder(0.012, pole_h), metal, name="pole", at=(0, 0, 0.025))
        shade = mk.frustum(0.17, 0.115, shade_h)
        b.add(shade, shade_m, name="shade", at=(0, 0, height - shade_h))
        bulb = mk.sphere(0.03, center=(0, 0, height - shade_h + 0.05))
        b.add(bulb, mk.mat.emissive("#fff3d0", 2.0), name="bulb")
    else:
        b.add(mk.cylinder(0.09, 0.02, sections=36), mk.mat.named_metal("steel", 0.5),
              name="base")
        arm_h = height * 0.72
        b.add(mk.cylinder(0.010, arm_h), metal, name="arm", at=(0, 0, 0.02))
        head = mk.frustum(0.10, 0.055, shade_h)
        mk.rot_x(head, 28.0)
        b.add(head, shade_m, name="shade", at=(0, -0.03, arm_h + 0.01))
        bulb = mk.sphere(0.018, center=(0, -0.045, arm_h + 0.02))
        b.add(bulb, mk.mat.emissive("#fff3d0", 2.0), name="bulb")
    return b
