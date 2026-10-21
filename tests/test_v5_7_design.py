"""v5.7 — non-régressions de la vague « qualité de design ».

Chaque test encode un défaut RÉELLEMENT mesuré, pas une intention :
  - l'albédo d'un blanc (pion, saladier, assiette) montait à 0.94 de luminance
    médiane : plus aucune réserve pour le grain ni pour la lumière ;
  - un asset 100 % verre (verre à vin) cassait tout le build (`concatenate`
    d'une liste vide de pièces opaques) ;
  - `Material(emissive=...)` devait accepter un hex ET un triplet HDR.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import game_ready as gr
import meshkit as mk
import pbr


def _weather(colors, metal=0.0):
    """Applique la patine à un nuage de points minimal (mêmes entrées que le bake."""
    n = len(colors)
    col = np.asarray(colors, dtype=np.float32).reshape(-1, 3)
    pos = np.column_stack([np.linspace(-0.05, 0.05, n), np.zeros(n), np.linspace(0, 0.1, n)])
    nrm = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (n, 1))
    bounds = np.stack([pos.min(0), pos.max(0)])
    out = gr.apply_game_weathering(
        col.copy(), np.full(n, 0.5, np.float32), np.full(n, metal, np.float32),
        np.full(n, 0.85, np.float32), np.full(n, 0.3, np.float32),
        pos.astype(np.float32), nrm, bounds, mat_id=np.zeros(n, np.int32),
    )
    return out[0]


@pytest.mark.parametrize("base", [1.0, 0.96, 0.92])
def test_albedo_blanc_garde_une_reserve_de_dynamique(base):
    """Un albédo clair ne doit jamais ressortir cramé (headroom perdu)."""
    col = _weather(np.tile([base, base * 0.98, base * 0.92], (400, 1)))
    lum = col @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    assert float(np.percentile(lum, 99)) <= 0.90, f"albédo cramé : p99 {np.percentile(lum, 99):.3f}"
    assert float(col.max()) <= 0.87


def test_compression_ne_touche_que_le_haut_de_lechelle():
    """La compression d'albédo est l'identité sous le genou, C1 au passage."""
    dark = np.array([[0.05, 0.20, 0.40], [0.60, 0.70, 0.72]], dtype=np.float32)
    out = gr.compress_albedo_headroom(dark)
    assert np.allclose(out, dark, atol=1e-6), "un albédo sous le genou a été altéré"
    # continuité : pas de marche d'escalier au niveau du genou
    k = 0.72
    eps = 1e-4
    lo = float(gr.compress_albedo_headroom(np.array([[k - eps]]))[0, 0])
    hi = float(gr.compress_albedo_headroom(np.array([[k + eps]]))[0, 0])
    assert abs(hi - lo) < 3e-3, f"discontinuité au genou : {lo:.4f} -> {hi:.4f}"


def test_asset_entierement_en_verre_ne_casse_pas(tmp_path):
    """`wine_glass` : toutes les pièces sont transparentes -> plus de corps opaque."""
    import turbo_forge

    res = turbo_forge.run_turbo("wine_glass", out_dir=str(tmp_path / "wg"))
    assert res["gates"]["all_pass"], res["gates"].get("n_pass")
    glb = tmp_path / "wg" / "wine_glass_game.glb"
    assert glb.is_file()
    import trimesh

    sc = trimesh.load(str(glb), process=False, force="scene")
    mats = [g.visual.material for g in sc.geometry.values() if getattr(g.visual, "material", None)]
    assert mats, "aucun matériau exporté"
    assert any(getattr(m, "alphaMode", None) == "BLEND" for m in mats), "le verre a perdu sa transparence"


def test_porcelaine_reste_claire_apres_patine():
    """Une porcelaine claire ne doit pas basculer au beige sale."""
    pale = _weather(np.tile([0.86, 0.85, 0.82], (400, 1))).mean(axis=0)
    lum = float(pale @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32))
    assert lum >= 0.72, f"la porcelaine s'est encrassée : luminance {lum:.3f}"
    # et elle ne vire pas : le bleu ne décroche pas du rouge
    assert abs(float(pale[0]) - float(pale[2])) < 0.09, f"dérive de teinte : {pale}"
