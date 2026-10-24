#!/usr/bin/env python3
"""Planche jeu / hero — `hero_compare.png`.

    PYTHONPATH=scripts python3 examples/g36_rifle/hero_compare.py

Deux maillages, les mêmes vues, le même éclairage : le GLB de jeu (6 336
triangles) et le hero (1 622 016). Le cadrage serré du bas est celui qui
compte : c'est là qu'on voit ce que la densité change — congés arrondis au
lieu d'une facette de 45°, grain de texture qui ne bave plus.
"""
from __future__ import annotations

import sys
from pathlib import Path

import trimesh
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import renderer as rn  # noqa: E402

GAME = ROOT / "exports" / "g36_rifle" / "g36_rifle_game.glb"
HERO = ROOT / "exports" / "g36_rifle" / "hero" / "g36_rifle_hero.glb"
OUT = HERE / "hero_compare.png"


def render(path: Path, az: float, el: float, fov: float, size: int) -> Image.Image:
    scene = trimesh.load(path, force="scene")
    return rn.render_view(scene, az, el, size=size, ssaa=1.0, fov=fov, post=True)


def counts(path: Path) -> int:
    scene = trimesh.load(path, force="scene")
    return sum(len(g.faces) for g in scene.geometry.values())


def main() -> int:
    for p in (GAME, HERO):
        if not p.is_file():
            print(f"absent : {p}", file=sys.stderr)
            return 1

    size = 900
    views = [("3/4 avant", -128.0, 16.0, 27.0), ("3/4 arriere", -38.0, 18.0, 27.0)]
    cells: list[tuple[str, Image.Image]] = []
    n_game, n_hero = counts(GAME), counts(HERO)

    for title, az, el, fov in views:
        for tag, path, n in (("jeu", GAME, n_game), ("hero", HERO, n_hero)):
            img = render(path, az, el, fov, size)
            cells.append((f"{title} — {tag} ({n:,} tris)".replace(",", " "), img))

    # cadrage serré : la zone des ouïes et du rail, seul endroit où la
    # différence de densité est franche à l'écran
    for tag, path, n in (("jeu", GAME, n_game), ("hero", HERO, n_hero)):
        img = render(path, -128.0, 16.0, 27.0, 1800)
        w, h = img.size
        crop = img.crop((int(w * 0.25), int(h * 0.33), int(w * 0.62), int(h * 0.60)))
        cells.append((f"detail — {tag} ({n:,} tris)".replace(",", " "), crop))

    pad, label_h = 12, 22
    cols, rows = 2, 3
    cw = max(c[1].width for c in cells)
    # hauteur de ligne réelle : les vignettes de détail sont plus petites que
    # les vues entières, une grille à hauteur unique laissait des trous
    row_h = [max(cells[r * cols + c][1].height for c in range(cols)
                 if r * cols + c < len(cells)) for r in range(rows)]
    W = pad + cols * (cw + pad)
    H = 34 + pad + sum(h + label_h + pad for h in row_h)
    sheet = Image.new("RGB", (W, H), (18, 19, 22))
    d = ImageDraw.Draw(sheet)
    d.text((pad, 8), "G36 — maillage de jeu vs maillage haute densite", fill=(190, 200, 210))

    y = 34 + pad
    for r in range(rows):
        for c in range(cols):
            i = r * cols + c
            if i >= len(cells):
                continue
            title, img = cells[i]
            x = pad + c * (cw + pad)
            sheet.paste(img, (x, y))
            d.text((x + 2, y + img.height + 5), title, fill=(150, 200, 230))
        y += row_h[r] + label_h + pad

    sheet.save(OUT)
    print(f"planche -> {OUT.relative_to(ROOT)}  ({sheet.width}x{sheet.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
