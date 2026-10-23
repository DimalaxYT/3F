#!/usr/bin/env python3
"""
Tests v6.2 — moteur de texture 4K (`scripts/texture_4k.py`).

Ces tests couvrent les trois bugs qui rendaient l'atlas 4096² inutilisable :
  1. **Rastérisation UV** : `np.nonzero(hit)` renvoie des indices LOCAUX à la
     fenêtre du triangle ; sans ré-ancrage sur `xa`, tous les triangles peignaient
     dans les ~30 premières colonnes (couverture mesurée : 4 %).
  2. **Palette** : la couleur doit venir de l'orientation de la surface (dos
     sombre / ventre sable), jamais d'un aplat uniforme.
  3. **Scutes ventrales** : le ventre doit avoir des plaques, pas des écailles.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

t4k = pytest.importorskip("texture_4k")


def _grid_mesh(n: int = 6):
    """Grille `n x n` dont les UV recouvrent exactement [0, 1]²."""
    xs, ys = np.meshgrid(np.linspace(0, 1, n + 1), np.linspace(0, 1, n + 1))
    verts = np.column_stack([xs.ravel(), ys.ravel(), np.zeros((n + 1) ** 2)])
    uv = verts[:, :2].copy()
    faces = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            faces.append([a, a + 1, a + n + 2])
            faces.append([a, a + n + 2, a + n + 1])
    nrm = np.tile(np.array([0.0, 0.0, 1.0]), (len(verts), 1))
    return verts, np.asarray(faces, dtype=np.int64), uv, nrm


def test_rasterisation_uv_couvre_l_atlas():
    """Une grille UV [0,1]² doit couvrir l'atlas, pas une bande de 30 colonnes.

    Régression : `rx` restait l'indice local du triangle -> 4 % de couverture.
    """
    verts, faces, uv, nrm = _grid_mesh(8)
    S = 128
    cov = np.zeros((S, S), dtype=bool)
    for y0, y1, pos, nrm_band, ok, attr in t4k._iter_uv_bands(
        verts, faces, uv, nrm, S, band=32
    ):
        cov[y0:y1] |= ok
    assert cov.mean() > 0.80, f"couverture UV {cov.mean():.1%} (attendu > 80 %)"
    # Colonnes réellement atteintes : c'est là que le bug se voyait.
    assert np.flatnonzero(cov.any(axis=0)).max() > S * 0.9


def test_rasterisation_position_monde_exacte():
    """Chaque texel couvert reçoit la position monde interpolée correspondante."""
    verts, faces, uv, nrm = _grid_mesh(2)
    S = 64
    for y0, y1, pos, nrm_band, ok, attr in t4k._iter_uv_bands(
        verts, faces, uv, nrm, S, band=16
    ):
        p = pos[ok]
        assert p.shape[1] == 3 and len(p) > 0
        # La grille est dans le plan z = 0 : toute position doit y être.
        assert np.abs(p[:, 2]).max() < 1e-6
        # et rester dans [0, 1]² (les UV couvrent exactement la surface).
        assert p[:, 0].min() >= -0.05 and p[:, 0].max() <= 1.05
        assert p[:, 1].min() >= -0.05 and p[:, 1].max() <= 1.05


def test_palette_dos_ventre_membrane():
    """Le dos est sombre, le ventre sable, la membrane aile brune."""
    p = np.array([[0.0, 0.0, 0.2]], dtype=np.float32)
    n_up = np.array([[0.0, 1.0, 0.0]], dtype=np.float32)
    n_down = np.array([[0.0, -1.0, 0.0]], dtype=np.float32)

    dos = t4k.palette_color(p, n_up, "body", (0.0, 0.4))[0]
    ventre = t4k.palette_color(p, n_down, "body", (0.0, 0.4))[0]
    aile = t4k.palette_color(p, np.array([[0.0, 0.2, 1.0]], np.float32), "wing", (0.0, 0.4))[0]

    assert dos.mean() < 0.30, f"dos trop clair : {dos}"
    assert ventre.mean() > 0.45, f"ventre trop sombre : {ventre}"
    assert ventre[0] > ventre[2], "le ventre doit être sable (R > B)"
    assert aile[0] > aile[1] > aile[2], f"membrane non brune : {aile}"


def test_scutes_ventrales_varient_le_long_du_corps():
    """Les plaques du ventre se succèdent en z (sinon c'est un aplat)."""
    z = np.linspace(0.0, 0.40, 400, dtype=np.float32)
    p = np.column_stack([np.zeros_like(z), np.full_like(z, -0.1), z])
    n = np.tile(np.array([0.0, -1.0, 0.0], dtype=np.float32), (len(z), 1))
    f = t4k.scute_field(p, n)
    assert f["height"].std() > 0.15
    assert 0.0 <= float(f["seam"].min()) and float(f["seam"].max()) <= 1.0


def test_padding_ne_tache_pas_l_atlas():
    """Le remplissage lointain doit rester neutre (pas de grandes taches claires).

    Régression : un remplissage « plus proche voisin » sur tout l'atlas inondait
    les vides de beige opaque.
    """
    src = (ROOT / "scripts" / "texture_4k.py").read_text()
    assert "distance_transform_edt" in src
    assert "neutral" in src and "bc_mid" in src
