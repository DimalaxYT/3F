#!/usr/bin/env python3
"""make_specs.py — construit les specs meshgen des 5 parties du katana
+ le manifest d'assemblage (Workflow D, scripts/assemble.py).

Katana vertical (pointe en haut), base z=0, ~0.98 m :
  kashira 0.000-0.033 · tsuka 0.033-0.303 · tsuba 0.303-0.311
  habaki 0.311-0.341 · lame 0.341-0.976 (sori vers +X, kissaki)

Les vues ASCII sont dessinées par code (put_row) avec vérification des
dimensions — même méthode que specs/epee_rouillee.json du skill.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "specs", "parts")
os.makedirs(OUT, exist_ok=True)


def grid(cols, rows, fill="."):
    return ["".join(fill for _ in range(cols)) for _ in range(rows)]


def put(g, r, c0, c1, ch):
    """Écrit ch sur la ligne r entre les colonnes c0..c1 (incluses)."""
    row = list(g[r])
    for c in range(c0, min(c1 + 1, len(row))):
        row[c] = ch
    g[r] = "".join(row)
    return g


def spec(name, prompt, size_m, res, palette, front, side, top, overlays=None,
         symmetry=True, smooth=8, budget=6000, texture=512, mc=0.5):
    # cohérence inter-vues : front.cols == top.cols, front.rows == side.rows,
    # side.cols == top.rows
    assert len(front[0]) == len(top[0]), f"{name}: X front={len(front[0])} top={len(top[0])}"
    assert len(front) == len(side), f"{name}: Z {len(front)} vs {len(side)}"
    assert len(side[0]) == len(top), f"{name}: Y {len(side[0])} vs {len(top)}"
    s = {"name": name, "prompt": prompt, "size_m": size_m, "res": res,
         "upsample": 2, "smooth": smooth, "budget_tris": budget,
         "symmetry_x": symmetry, "mc_level": mc, "texture_size": texture,
         "palette": palette,
         "views": {"front": front, "side": side, "top": top}}
    if overlays:
        s["overlays"] = overlays
    p = os.path.join(OUT, name + ".json")
    with open(p, "w") as fh:
        json.dump(s, fh, indent=2, ensure_ascii=False)
    print(f"spec  {name:10s} front {len(front[0])}x{len(front)}  -> {p}")
    return p


# ---------------------------------------------------------------- kashira ---
# Capuchon arrondi (laque noire), 33 mm — largeur calée sur la tsuka (~2 cm)
C, R = 9, 8
f = grid(C, R)
for r in range(1, 7):
    put(f, r, 2, 6, "#")
put(f, 0, 3, 5, "#")
put(f, 7, 3, 5, "#")
s = grid(6, R)
for r in range(1, 7):
    put(s, r, 1, 5, "#")
put(s, 0, 2, 3, "#")
put(s, 7, 2, 3, "#")
t = grid(C, 6)
put(t, 0, 3, 5, "#")
for r in range(1, 5):
    put(t, r, 2, 6, "#")
put(t, 5, 3, 5, "#")
kashira = spec("kashira", "kashira (capuchon) de katana, laque noire", 0.033, 48,
               [{"id": "#", "name": "laque", "color": "#1c1c20",
                 "metallic": 0.15, "roughness": 0.35}],
               f, s, t, budget=2000)

# ------------------------------------------------------------------ tsuka ---
# Poignée wrappée (ito noir sur same), 270 mm
C, R = 5, 40
f = grid(C, R)
for r in range(R):
    put(f, r, 1, 3, "#")
s = grid(3, R)
for r in range(R):
    put(s, r, 0, 2, "#")
t = grid(C, 3)
for r in range(3):
    put(t, r, 0, 4, "#")
tsuka = spec("tsuka", "tsuka (poignée) de katana, ito noir wrappé sur same", 0.27,
             72,
             [{"id": "#", "name": "ito", "color": "#26262b",
               "metallic": 0.0, "roughness": 0.82}],
             f, s, t,
             overlays=[{"type": "wrap", "on": "#", "count": 11,
                        "twist": 0.42, "darken": 0.5}],
             budget=4000, texture=512, smooth=6)

# ------------------------------------------------------------------ tsuba ---
# Garde : disque Ø80 mm, épaisseur 8 mm. Dessinée SUR TRANCHE (disque vertical
# dans son propre repère : le rond est dans la vue face X×Z), puis couchée
# à plat dans le manifest via rot_deg [90,0,0]. Évite une grille voxelle
# 960×960×96 (aspect 10:1 à plat = OOM).
C, R = 80, 80          # front (X×Z) : le disque
f = grid(C, R)
cx, cy, rad = C / 2 - 0.5, R / 2 - 0.5, C / 2
for r in range(R):
    dy = r - cy
    half = int((rad * rad - dy * dy) ** 0.5) if abs(dy) <= rad else -1
    if half >= 0:
        put(f, r, int(cx - half), int(cx + half), "#")
s = grid(8, R)          # side (Y×Z) : épaisseur 8 cellules = 8 mm
for r in range(R):
    put(s, r, 0, 7, "#")
t = grid(C, 8)          # top (X×Y) : empreinte, couvre tout
for r in range(8):
    put(t, r, 0, C - 1, "#")
tsuba = spec("tsuba", "tsuba (garde) de katana, fer sombre patiné", 0.08, 96,
             [{"id": "#", "name": "fer", "color": "#3a3d42",
               "metallic": 0.85, "roughness": 0.52}],
             f, s, t, budget=6000, texture=512, smooth=3, mc=0.5)

# ---------------------------------------------------------------- habaki ---
# Collerette laiton, 30 mm
C, R = 12, 10
f = grid(C, R)
for r in range(R):
    put(f, r, 1, 10, "#")
s = grid(8, R)
for r in range(R):
    put(s, r, 0, 7, "#")
t = grid(C, 8)
for r in range(8):
    put(t, r, 0, C - 1, "#")
habaki = spec("habaki", "habaki (collerette) de katana, laiton doré", 0.03, 64,
              [{"id": "#", "name": "laiton", "color": "#b08d3e",
                "metallic": 1.0, "roughness": 0.34}],
              f, s, t, budget=3000, smooth=6)

# ------------------------------------------------------------------- lame ---
# Lame courbée (sori 15 mm vers +X), kissaki, 635 mm — 2 px d'épaisseur
VOX = 0.635 / 96
ROWS = 96
WID = 4           # largeur lame (cols) ~2.6 cm
THICK = 2         # épaisseur (cols, vue side) ~1.3 cm
f = grid(WID + 4, ROWS)
for r in range(ROWS):
    h_frac = 1.0 - r / (ROWS - 1)                   # 1 = bas, 0 = pointe
    off = round(0.015 * (1.0 - h_frac) ** 1.6 / VOX)  # sori -> +X vers le haut
    c0 = 2 + off
    w = WID
    if r == 0:
        w = 1
    elif r == 1:
        w = 2
    elif r == 2:
        w = 3
    put(f, r, c0, c0 + w - 1, "#")
s = grid(THICK + 2, ROWS)
for r in range(ROWS):
    put(s, r, 1, 1 + THICK - 1, "#")
TC, TR = WID + 4, THICK + 2
t = grid(TC, TR)
for r in range(TR):
    put(t, r, 0, TC - 1, "#")
lame = spec("lame", "lame de katana courbée, acier poli, kissaki", 0.635, 96,
            [{"id": "#", "name": "acier", "color": "#b9bec6",
              "metallic": 0.95, "roughness": 0.3}],
            f, s, t,
            overlays=[{"type": "edge_wear", "on": ["#"], "amount": 0.45,
                       "scale": 16.0}],
            symmetry=False, smooth=4, budget=9000, texture=1024, mc=0.47)

# --------------------------------------------------------------- manifest ---
# at = position du CENTRE de chaque partie (assemble.py centre les bboxes).
# Chevauchements 1-3 mm entre parties consécutives : les unions booléennes
# face-à-face exactes sont fragiles, l'interpénétration est robuste.
manifest = {
    "name": "katana",
    "prompt": "katana forgé — lame courbée polie, tsuba de fer, tsuka wrappée "
              "ito noir, habaki laiton, kashira laqué (0.97 m)",
    "size_m": 0.969,
    "parallel": True,
    "parts": [
        {"id": "kashira", "spec": "specs/parts/kashira.json", "at": [0, 0, 0.018]},
        {"id": "tsuka",   "spec": "specs/parts/tsuka.json",   "at": [0, 0, 0.1665]},
        {"id": "tsuba",   "spec": "specs/parts/tsuba.json",   "at": [0, 0, 0.3035],
         "rot_deg": [90, 0, 0]},
        {"id": "habaki",  "spec": "specs/parts/habaki.json",  "at": [0, 0, 0.3215]},
        {"id": "lame",    "spec": "specs/parts/lame.json",    "at": [0, 0, 0.6515]},
    ],
}
mp = os.path.join(HERE, "manifest.json")
with open(mp, "w") as fh:
    json.dump(manifest, fh, indent=2, ensure_ascii=False)
print(f"manifest -> {mp}")
