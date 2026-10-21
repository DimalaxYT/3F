"""
Génère les specs de pièces + l'assembly spec pour un katana + fourreau (Workflow D).

Chaque pièce a SA grille dédiée (haute résolution sur son volume utile, plus de
diluer 1 m de lame sur 256 voxels) et SES vues vectorielles lisses (`meshgen` v2 :
`spline`, `ellipse`, `capsule`, `erase`).

Conventions d'axes (partagées avec `meshgen` et `assemble`) :
  X : largeur lame (dos mune -X -> tranchant ha +X), la courbe sori part en -X
  Y : épaisseur (plat de la lame)
  Z : longueur (0 = kashira au bout de poignée -> ~0.99 m kissaki)

Usage :
  python3 examples/katana/make_specs.py
  python3 scripts/assemble.py examples/katana/assembly.json --out examples/katana --name katana --force
"""
from __future__ import annotations

import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARTS = HERE / "parts_spec"
PARTS.mkdir(parents=True, exist_ok=True)


def sori_curve(t: float) -> float:
    """Courbure japonaise sori (m) centrée dans sa boîte englobante."""
    return 0.0085 - 0.0195 * (t ** 1.75)


def write_spec(name: str, spec: dict) -> str:
    p = PARTS / f"{name}.json"
    p.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    # Chemin relatif au dossier du manifest (zéro chemin local dans report.json)
    return str(p.relative_to(HERE))


# ======================================================================== LAME
def make_blade() -> tuple[str, list[float]]:
    L = 0.705       # 68.5 cm nagasa + 2 cm sous le habaki
    XSPAN = 0.049
    YSPAN = 0.0080
    W, WS, H = 160, 64, 512

    center_front = []
    hw_front = []
    center_side = []
    hw_side = []
    for k in range(33):
        t = k / 32.0                # 0 = base (y = H), 1 = kissaki (y = 0)
        py = round((1.0 - t) * (H - 4) + 2, 2)
        cx_m = sori_curve(t)
        px = round((cx_m / XSPAN + 0.5) * W, 2)
        w_m = 0.0315 * (1.0 - 0.24 * (t ** 1.15))
        th_m = 0.0076 * (1.0 - 0.34 * t)
        if t > 0.90:
            u = (t - 0.90) / 0.10
            w_m *= max(0.06, (1.0 - u) ** 0.80)
            th_m *= max(0.14, 1.0 - 0.84 * u)
        center_front.append([py, px])
        hw_front.append([py, max(0.8, round(w_m / XSPAN * W * 0.5, 2))])
        center_side.append([py, WS * 0.5])
        hw_side.append([py, max(2.2, round(th_m / YSPAN * WS * 0.5, 2))])

    # Bo-hi (gorge de sang côté dos -X) sur les 2/3 inférieurs
    hi_center, hi_hw = [], []
    for k in range(22):
        t = 0.04 + 0.66 * (k / 21.0)
        py = round((1.0 - t) * (H - 4) + 2, 2)
        w_m = 0.0315 * (1.0 - 0.24 * (t ** 1.15))
        cx_m = sori_curve(t) - w_m * 0.26
        hi_center.append([py, round((cx_m / XSPAN + 0.5) * W, 2)])
        hi_hw.append([py, round(0.0044 / XSPAN * W * 0.5, 2)])

    spec = {
        "name": "blade",
        "dims": [XSPAN, YSPAN, L],
        "grid": [96, 32, 192],
        "symmetry_x": False,
        "smooth": 4,
        "sdf_sigma": 0.7,
        "budget_tris": 12000,
        "texture_size": 1024,
        "normal_strength": 1.6,
        "materials": {
            "steel": {"base": "#cfd4da", "roughness": 0.16, "metallic": 0.95},
            "hi":    {"base": "#969da6", "roughness": 0.30, "metallic": 0.92},
        },
        "overlays": [
            {"type": "brushed_metal", "on": ["steel", "hi"], "axis": "z", "scale": 190.0, "amount": 0.10},
            {"type": "hamon", "on": "steel", "axis": "x", "positive_edge": True, "edge_frac": 0.62, "freq": 64.0},
            {"type": "edge_wear", "on": "steel", "amount": 0.42, "scale": 22.0, "seed": 3},
        ],
        "views": {
            "front": {
                "size": [W, H],
                "shapes": [
                    {"op": "spline", "mat": "steel",
                     "center": list(reversed(center_front)),
                     "half_width": list(reversed(hw_front))},
                    {"op": "spline", "mat": "hi",
                     "center": list(reversed(hi_center)),
                     "half_width": list(reversed(hi_hw))},
                ],
            },
            "side": {
                "size": [WS, H],
                "shapes": [
                    {"op": "spline", "mat": "steel",
                     "center": list(reversed(center_side)),
                     "half_width": list(reversed(hw_side))},
                ],
            },
            "top": {
                "size": [W, WS],
                "shapes": [
                    {"op": "rect", "mat": "steel", "x0": 3, "y0": 4, "x1": W - 3, "y1": WS - 4, "r": 10},
                ],
            },
        },
    }
    return write_spec("blade", spec), [-0.005, 0.0, 0.654]


# ====================================================================== HABAKI
def make_habaki() -> tuple[str, list[float]]:
    X, Y, Z = 0.036, 0.013, 0.032
    spec = {
        "name": "habaki",
        "dims": [X, Y, Z],
        "grid": [80, 48, 64],
        "smooth": 3,
        "texture_size": 512,
        "normal_strength": 1.4,
        "materials": {"brass": {"base": "#c89b3c", "roughness": 0.26, "metallic": 0.94}},
        "overlays": [
            {"type": "brushed_metal", "on": "brass", "axis": "z", "scale": 140.0, "amount": 0.14},
            {"type": "edge_wear", "on": "brass", "amount": 0.45, "scale": 26.0, "seed": 5},
        ],
        "views": {
            "front": {"size": [192, 192], "shapes": [
                {"op": "poly", "mat": "brass", "pts": [[16, 8], [176, 8], [186, 184], [6, 184]]},
            ]},
            "side": {"size": [192, 192], "shapes": [
                {"op": "poly", "mat": "brass", "pts": [[24, 8], [168, 8], [180, 184], [12, 184]]},
            ]},
            "top": {"size": [192, 192], "shapes": [
                {"op": "poly", "mat": "brass", "pts": [[8, 96], [84, 16], [184, 88], [184, 104], [84, 176]]},
            ]},
        },
    }
    return write_spec("habaki", spec), [0.0, 0.0, 0.304]


# ======================================================================= TSUBA
def make_tsuba() -> tuple[str, list[float]]:
    D, T = 0.082, 0.0085
    W = 256
    shapes_top = [
        {"op": "circle", "mat": "bronze", "cx": 128, "cy": 128, "r": 120},
        {"op": "circle", "mat": "rim",    "cx": 128, "cy": 128, "r": 120},
        {"op": "circle", "mat": "bronze", "cx": 128, "cy": 128, "r": 106},
    ]
    for ang_deg in (45, 135, 225, 315):
        a = math.radians(ang_deg)
        shapes_top.append({
            "op": "circle", "mat": "void",
            "cx": round(128 + 64 * math.cos(a), 1),
            "cy": round(128 + 64 * math.sin(a), 1),
            "r": 21.0,
        })

    spec = {
        "name": "tsuba",
        "dims": [D, D, T],
        "grid": [112, 112, 32],
        "smooth": 2,
        "fill_cavities": False,
        "texture_size": 512,
        "normal_strength": 1.8,
        "materials": {
            "bronze": {"base": "#5b4834", "roughness": 0.44, "metallic": 0.88},
            "rim":    {"base": "#8f7144", "roughness": 0.30, "metallic": 0.92},
        },
        "overlays": [
            {"type": "patina", "on": ["bronze", "rim"], "color": "#2f2a22", "amount": 0.35, "scale": 28.0, "seed": 9},
            {"type": "edge_wear", "on": ["bronze", "rim"], "amount": 0.62, "scale": 24.0, "seed": 12},
        ],
        "views": {
            "front": {"size": [W, 96], "shapes": [
                {"op": "rect", "mat": "rim", "x0": 8, "y0": 10, "x1": W - 8, "y1": 86, "r": 18},
            ]},
            "side": {"size": [W, 96], "shapes": [
                {"op": "rect", "mat": "rim", "x0": 8, "y0": 10, "x1": W - 8, "y1": 86, "r": 18},
            ]},
            "top": {"size": [W, W], "shapes": shapes_top},
        },
    }
    return write_spec("tsuba", spec), [0.0, 0.0, 0.288]


# ======================================================================= TSUKA
def make_tsuka() -> tuple[str, list[float]]:
    X, Y, L = 0.040, 0.026, 0.268
    W, H = 192, 384
    spec = {
        "name": "tsuka",
        "dims": [X, Y, L],
        "grid": [80, 64, 160],
        "smooth": 3,
        "texture_size": 1024,
        "normal_strength": 2.4,
        "materials": {
            "ito":   {"base": "#1b1d24", "roughness": 0.82, "metallic": 0.03},
            "fuchi": {"base": "#2b2622", "roughness": 0.34, "metallic": 0.88},
        },
        "overlays": [
            {"type": "wrap", "on": "ito", "diamond": True, "under_color": "#e2dac6",
             "count": 9.5, "ribbon_width": 0.35},
            {"type": "edge_wear", "on": "fuchi", "amount": 0.58, "scale": 24.0, "seed": 17},
        ],
        "views": {
            "front": {"size": [W, H], "shapes": [
                {"op": "spline", "mat": "ito",
                 "center": [[6, 96], [192, 99], [378, 96]],
                 "half_width": [[6, 78], [28, 75], [192, 68], [356, 74], [378, 78]]},
                {"op": "rect", "mat": "fuchi", "x0": 14, "y0": 4, "x1": 178, "y1": 30, "r": 6},
            ]},
            "side": {"size": [W, H], "shapes": [
                {"op": "spline", "mat": "ito",
                 "center": [[6, 96], [378, 96]],
                 "half_width": [[6, 78], [28, 74], [192, 69], [356, 74], [378, 78]]},
                {"op": "rect", "mat": "fuchi", "x0": 14, "y0": 4, "x1": 178, "y1": 30, "r": 6},
            ]},
            "top": {"size": [W, W], "shapes": [
                {"op": "ellipse", "mat": "ito", "cx": 96, "cy": 96, "rx": 82, "ry": 82},
            ]},
        },
    }
    return write_spec("tsuka", spec), [0.0, 0.0, 0.154]


# ===================================================================== KASHIRA
def make_kashira() -> tuple[str, list[float]]:
    X, Y, Z = 0.039, 0.025, 0.026
    spec = {
        "name": "kashira",
        "dims": [X, Y, Z],
        "grid": [72, 56, 56],
        "smooth": 4,
        "budget_tris": 4000,
        "texture_size": 512,
        "normal_strength": 1.5,
        "materials": {
            "horn": {"base": "#231f22", "roughness": 0.28, "metallic": 0.86},
            "cord": {"base": "#c89b3c", "roughness": 0.30, "metallic": 0.92},
        },
        "overlays": [
            {"type": "edge_wear", "on": ["horn", "cord"], "amount": 0.55, "scale": 26.0, "seed": 23},
        ],
        "views": {
            "front": {"size": [192, 160], "shapes": [
                {"op": "rect", "mat": "horn", "x0": 12, "y0": 8, "x1": 180, "y1": 148, "r": 34},
                {"op": "ellipse", "mat": "cord", "cx": 96, "cy": 72, "rx": 24, "ry": 14},
            ]},
            "side": {"size": [192, 160], "shapes": [
                {"op": "rect", "mat": "horn", "x0": 14, "y0": 8, "x1": 178, "y1": 148, "r": 34},
            ]},
            "top": {"size": [192, 192], "shapes": [
                {"op": "ellipse", "mat": "horn", "cx": 96, "cy": 96, "rx": 86, "ry": 84},
            ]},
        },
    }
    return write_spec("kashira", spec), [0.0, 0.0, 0.013]


# ======================================================================== SAYA
def make_saya() -> tuple[str, list[float]]:
    L = 0.735
    XSPAN = 0.058
    YSPAN = 0.022
    W, WS, H = 160, 72, 512

    center_front, hw_front = [], []
    for k in range(33):
        t = k / 32.0
        py = round((1.0 - t) * (H - 6) + 3, 2)
        cx_m = sori_curve(t)
        w_m = 0.040 * (1.0 - 0.16 * t)
        center_front.append([py, round((cx_m / XSPAN + 0.5) * W, 2)])
        hw_front.append([py, round(w_m / XSPAN * W * 0.5, 2)])

    spec = {
        "name": "saya",
        "dims": [XSPAN, YSPAN, L],
        "grid": [88, 40, 176],
        "symmetry_x": False,
        "smooth": 4,
        "sdf_sigma": 0.75,
        "budget_tris": 10000,
        "texture_size": 1024,
        "normal_strength": 1.5,
        "materials": {
            "lacquer":  {"base": "#17161a", "roughness": 0.18, "metallic": 0.05},
            "koiguchi": {"base": "#2f241c", "roughness": 0.32, "metallic": 0.10},
            "kurigata": {"base": "#c89b3c", "roughness": 0.30, "metallic": 0.90},
        },
        "overlays": [
            {"type": "speckle", "on": "lacquer", "amount": 0.05, "scale": 130.0, "seed": 21},
            {"type": "edge_wear", "on": ["koiguchi", "kurigata"], "amount": 0.45, "scale": 24.0, "seed": 13},
        ],
        "views": {
            "front": {"size": [W, H], "shapes": [
                {"op": "spline", "mat": "lacquer",
                 "center": list(reversed(center_front)),
                 "half_width": list(reversed(hw_front))},
                {"op": "rect", "mat": "koiguchi", "x0": 34, "y0": 488, "x1": 146, "y1": 509, "r": 5},
                {"op": "ellipse", "mat": "kurigata", "cx": 42, "cy": 432, "rx": 14, "ry": 20},
            ]},
            "side": {"size": [WS, H], "shapes": [
                {"op": "spline", "mat": "lacquer",
                 "center": [[3, WS * 0.5], [509, WS * 0.5]],
                 "half_width": [[3, 22], [32, 27], [488, 33], [509, 34]]},
                {"op": "rect", "mat": "koiguchi", "x0": 3, "y0": 488, "x1": WS - 3, "y1": 509, "r": 4},
            ]},
            "top": {"size": [W, WS], "shapes": [
                {"op": "rect", "mat": "lacquer", "x0": 4, "y0": 4, "x1": W - 4, "y1": WS - 4, "r": 16},
            ]},
        },
    }
    return write_spec("saya", spec), [0.095, 0.0, 0.0]


def main():
    parts = []
    for fn in (make_kashira, make_tsuka, make_tsuba, make_habaki, make_blade):
        spec_rel, pos = fn()
        parts.append({"id": Path(spec_rel).stem, "spec": spec_rel, "at": pos})
    assembly = {
        "name": "katana",
        "prompt": "katana japonais traditionnel forgé (5 parties assemblées)",
        "parts": parts,
    }
    out = HERE / "assembly.json"
    out.write_text(json.dumps(assembly, indent=2), encoding="utf-8")
    print(f"écrit : {out.relative_to(HERE.parent.parent)}  ({len(parts)} pièces)")


if __name__ == "__main__":
    main()
