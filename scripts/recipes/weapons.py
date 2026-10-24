"""Recette G36 — Heckler & Koch G36E (5,56 × 45 mm).

Source unique : `examples/g36_rifle/build_g36.py`. La recette catalogue ne
duplique plus la géométrie, elle charge le builder livré et le pose au sol.
Ainsi `turbo_forge.py g36` produit **exactement** l'arme validée sur photo.

Le G36 est construit en **hard-surface** : silhouettes anguleuses extrudées,
sections chanfreinées à 2,2 mm, faces planes. Plus aucun loft de rectangles
arrondis (c'était la faute de la v1 : 40 % de chaque flanc en congé, aucun
plan, rendu « savon »).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import meshkit as mk
from .registry import register

_ROOT = Path(__file__).resolve().parents[2]
_BUILD_G36 = _ROOT / "examples" / "g36_rifle" / "build_g36.py"
_MODULE = None


def _g36_module():
    """Charge (une fois) le builder de `examples/g36_rifle/build_g36.py`."""
    global _MODULE
    if _MODULE is None:
        if not _BUILD_G36.exists():
            raise FileNotFoundError(f"builder G36 introuvable : {_BUILD_G36}")
        spec = importlib.util.spec_from_file_location("g36_example_build", _BUILD_G36)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MODULE = mod
    return _MODULE


@register("g36",
          defaults={},
          info=[{"name": "n/a", "type": "str",
                 "help": "Aucun paramètre : cotes réelles mesurées sur photo (998 mm)"}])
def build_g36_registered() -> mk.Builder:
    """G36E hard-surface, posé au sol, avec sockets gameplay (`muzzle`, `grip`, `optic`…)."""
    mod = _g36_module()
    return mod.ground(mod.build())
