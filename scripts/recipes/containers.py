"""Recettes contenants & objets de révolution : mug, vase, bottle, bowl, plate,
wine_glass, chess_pawn. Tous les profils lathe partent et finissent sur l'axe
→ solides étanches, prêts pour l'impression 3D."""
from __future__ import annotations
import numpy as np
from scipy.interpolate import PchipInterpolator
from .registry import register
import meshkit as mk


def _spline_profile(zt, rt, n=36):
    """Interpole des points de contrôle (z normalisé, r relatif) en profil dense.
    PCHIP : préserve la forme, jamais d'overshoot entre points de contrôle."""
    cs = PchipInterpolator(zt, rt)
    z = np.linspace(zt[0], zt[-1], n)
    r = np.clip(cs(z), 0.002, None)
    return list(zip(r, z))


@register("mug", defaults={"height": 0.095, "radius": 0.04, "color": "#e8e4dc",
                           "handle": True},
          info=[{"name": "height", "type": "float", "help": "Hauteur en m"},
                {"name": "radius", "type": "float"},
                {"name": "color", "type": "color"},
                {"name": "handle", "type": "bool", "help": "Ajouter l'anse"}])
def build_mug(height=0.095, radius=0.04, color="#e8e4dc", handle=True):
    b = mk.Builder("mug", {"handle": handle})
    ceramic = mk.mat.ceramic(color)
    wall = min(0.005, radius * 0.14)
    profile = [(0, 0), (radius, 0), (radius, height),
               (radius - wall, height), (radius - wall, wall), (0, wall)]
    body = mk.lathe(profile, sections=48, smooth=False)
    b.add(body, ceramic, name="body")
    if handle:
        R = height * 0.30
        handle_mesh = mk.torus(R, 0.0075, major=24, minor=12, center=(0, 0, 0))
        mk.rot_x(handle_mesh, 90)              # plan vertical XZ
        b.add(handle_mesh, ceramic, name="handle",
              at=(radius * 0.98, 0, height * 0.52))
    return b


@register("vase", defaults={"shape": "amphora", "height": 0.30, "radius": 0.08,
                            "color": "#8b3a2a"},
          info=[{"name": "shape", "type": "choice",
                 "choices": ["amphora", "bulb", "cylinder", "flask"]},
                {"name": "height", "type": "float"},
                {"name": "radius", "type": "float", "help": "Rayon maximal"},
                {"name": "color", "type": "color"}])
def build_vase(shape="amphora", height=0.30, radius=0.08, color="#8b3a2a"):
    shapes = {
        "amphora": ([0.00, 0.02, 0.35, 0.42, 0.68, 0.88, 0.94, 1.00],
                    [0.40, 0.56, 0.98, 1.00, 0.68, 0.40, 0.36, 0.52]),
        "bulb":    ([0.00, 0.05, 0.32, 0.70, 1.00],
                    [0.42, 0.85, 1.00, 0.50, 0.38]),
        "cylinder": ([0.00, 0.05, 0.90, 1.00],
                     [0.85, 1.00, 1.00, 0.88]),
        "flask":   ([0.00, 0.04, 0.25, 0.55, 0.75, 1.00],
                    [0.45, 0.95, 1.00, 0.40, 0.18, 0.22]),
    }
    zt, rt = shapes[shape]
    profile = _spline_profile(zt, rt, n=40)
    profile = [(r * radius, z * height) for r, z in profile]
    b = mk.Builder("vase", {"shape": shape})
    b.add(mk.lathe(profile, sections=64), mk.mat.ceramic(color, 0.22), name="body")
    return b


@register("bottle", defaults={"height": 0.25, "radius": 0.035,
                              "color": "#7fa8a0", "cap": True},
          info=[{"name": "height", "type": "float"},
                {"name": "radius", "type": "float"},
                {"name": "color", "type": "color", "help": "Teinte du verre"},
                {"name": "cap", "type": "bool"}])
def build_bottle(height=0.25, radius=0.035, color="#7fa8a0", cap=True):
    zt = [0.00, 0.03, 0.55, 0.68, 0.80, 0.97, 1.00]
    rt = [0.60, 1.00, 1.00, 0.80, 0.35, 0.32, 0.40]
    profile = _spline_profile(zt, rt, n=44)
    profile = [(r * radius, z * height) for r, z in profile]
    b = mk.Builder("bottle", {"cap": cap})
    glass = mk.mat.glass(color, opacity=0.38, roughness=0.04)
    b.add(mk.lathe(profile, sections=56), glass, name="body")
    if cap:
        neck_r = profile[-2][0]
        b.add(mk.cylinder(neck_r * 1.05, 0.014, sections=32),
              mk.mat.rubber("#3a3a3a", 0.6), name="cap",
              at=(0, 0, height + 0.002))
    return b


@register("bowl", defaults={"radius": 0.09, "height": 0.05, "color": "#dcd4c4",
                            "wall": 0.006},
          info=[{"name": "radius", "type": "float"},
                {"name": "height", "type": "float"},
                {"name": "color", "type": "color"},
                {"name": "wall", "type": "float", "help": "Épaisseur de paroi"}])
def build_bowl(radius=0.09, height=0.05, color="#dcd4c4", wall=0.006):
    wall = min(wall, radius * 0.2)
    outer = _spline_profile([0.0, 0.25, 0.7, 1.0],
                            [0.45, 0.72, 0.95, 1.0], n=22)
    outer = [(r * radius, z * height) for r, z in outer]
    inner = [(r - wall, z) for r, z in reversed(outer)]
    profile = outer + inner                      # remonte l'extérieur, redescend l'intérieur
    b = mk.Builder("bowl", {})
    b.add(mk.lathe(profile, sections=56), mk.mat.ceramic(color), name="body")
    return b


@register("plate", defaults={"radius": 0.12, "color": "#e9e6de"},
          info=[{"name": "radius", "type": "float"},
                {"name": "color", "type": "color"}])
def build_plate(radius=0.12, color="#e9e6de"):
    profile = [(0, 0.004), (radius * 0.55, 0.005), (radius * 0.80, 0.010),
               (radius * 0.97, 0.020), (radius, 0.023),
               (radius - 0.004, 0.019), (radius * 0.78, 0.009),
               (radius * 0.55, 0.010), (0, 0.010)]
    b = mk.Builder("plate", {})
    b.add(mk.lathe(profile, sections=64, smooth=False),
          mk.mat.ceramic(color), name="body")
    return b


@register("wine_glass", defaults={"height": 0.20, "color": "#d5e8ee"},
          info=[{"name": "height", "type": "float"},
                {"name": "color", "type": "color", "help": "Teinte du verre"}])
def build_wine_glass(height=0.20, color="#d5e8ee"):
    # Profil PCHIP dense (quads quasi carrés -> zéro strie d'ondulation Taubin)
    ext = _spline_profile(
        [0.000, 0.018, 0.045, 0.095, 0.480, 0.560, 0.650, 0.800, 0.930, 1.000],
        [0.185, 0.190, 0.085, 0.022, 0.021, 0.036, 0.145, 0.215, 0.212, 0.198],
        n=42,
    )
    cav = _spline_profile(
        [0.585, 0.655, 0.800, 0.930, 1.000],
        [0.012, 0.132, 0.201, 0.199, 0.186],
        n=26,
    )
    profile = ([(0.0, 0.0)]
               + [(r * height, z * height) for r, z in ext]
               + [(r * height, z * height) for r, z in reversed(cav)]
               + [(0.0, 0.580 * height)])
    b = mk.Builder("wine_glass", {})
    b.add(mk.lathe(profile, sections=64, smooth=False),
          mk.mat.glass(color, 0.42, 0.04), name="body")
    return b


@register("chess_pawn", defaults={"height": 0.06, "color": "#f0ead6"},
          info=[{"name": "height", "type": "float"},
                {"name": "color", "type": "color"}])
def build_chess_pawn(height=0.06, color="#f0ead6"):
    zt = [0.00, 0.05, 0.12, 0.28, 0.48, 0.55, 0.62, 0.72, 0.85, 0.95, 1.00]
    rt = [0.30, 0.30, 0.22, 0.14, 0.11, 0.17, 0.13, 0.16, 0.20, 0.15, 0.02]
    profile = _spline_profile(zt, rt, n=48)
    profile = [(r * height, z * height) for r, z in profile]
    b = mk.Builder("chess_pawn", {})
    b.add(mk.lathe(profile, sections=56), mk.mat.plastic(color, 0.25), name="body")
    return b
