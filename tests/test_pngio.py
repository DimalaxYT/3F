"""`pngio.fast_png` : le niveau de compression doit réellement s'appliquer et le
handler PIL doit être restauré (le piège historique : patcher
`PngImagePlugin._save` ne change RIEN car PIL fige sa table `Image.SAVE`).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import pngio  # noqa: E402


def test_fast_png_applique_le_niveau_et_restaure(tmp_path):
    original_handler = Image.SAVE["PNG"]
    real_save = pngio._ORIG_PNG_SAVE
    levels: list = []

    def spy(im, fp, filename, *a, **kw):
        levels.append(im.encoderinfo.get("compress_level"))
        return real_save(im, fp, filename, *a, **kw)

    pngio._ORIG_PNG_SAVE = spy
    try:
        with pngio.fast_png(pngio.QA_LEVEL):
            Image.new("RGB", (32, 32), (255, 0, 0)).save(tmp_path / "qa.png")
        assert levels == [pngio.QA_LEVEL], "le niveau n'a pas été forcé"
        # le contexte restaure l'original du module (ici le spy)
        assert Image.SAVE["PNG"] is spy, "handler PNG non restauré"

        levels.clear()
        Image.new("RGB", (8, 8), (0, 0, 255)).save(tmp_path / "plain.png")
        # hors contexte, le niveau n'est plus forcé (PIL garde son défaut)
        assert levels == [None], "fast_png fuit hors de son contexte"
    finally:
        pngio._ORIG_PNG_SAVE = real_save
        Image.SAVE["PNG"] = original_handler      # nettoyage complet de l'instrumentation
    assert Image.SAVE["PNG"] is original_handler


def test_fast_png_produit_un_png_valide(tmp_path):
    im = Image.new("RGB", (64, 64), (12, 34, 56))
    out = tmp_path / "x.png"
    with pngio.fast_png():
        im.save(out)
    again = Image.open(out)
    assert again.format == "PNG"
    assert again.size == (64, 64)
    assert again.getpixel((10, 10)) == (12, 34, 56)


def test_emissive_hex_et_triplet():
    """Régression : `Material(emissive="#00e5ff")` (hex) a cassé tout le pipeline ;
    `mk.mat.emissive(color, 2.6)` (triplet) doit conserver sa force HDR."""
    import meshkit as mk

    m = mk.Material("t", "#ffffff", emissive="#00e5ff")
    assert m._emissive_strength == 1.0
    assert abs(float(m.emissive[2]) - 1.0) < 1e-6      # canal le plus fort -> 1.0

    m2 = mk.mat.emissive("#3af0ff", 2.6)
    assert abs(m2._emissive_strength - 2.6) < 1e-6
    assert float(m2.emissive.max()) <= 1.0 + 1e-9      # chromaticité bornée
