"""Test de fumée : construit chaque recette (qualité réduite), vérifie étanchéité
du solide fusionné + export GLB. Exécutable via `pytest` OU directement en CLI."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # racine skill
if os.path.join(HERE, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(HERE, "scripts"))

import meshkit as mk                              # noqa: E402
from recipes import catalog, get as get_recipe    # noqa: E402


def run_smoke(verbose: bool = True) -> list[str]:
    prev_q = mk._QUALITY
    mk.set_quality(0.5)
    fails = []
    try:
        if verbose:
            print(f"{'recette':14s} {'pièces':>6s} {'tris':>7s}  {'étanche':7s} {'vol>0':5s}  dims (m)")
        for name in catalog():
            try:
                meta = get_recipe(name)
                builder = meta["builder"](**meta["defaults"])
                solid = builder.union_solid()
                wt = solid.is_watertight
                vol = solid.volume > 0 if wt else False
                st = builder.stats()
                flag = "OK" if (wt and vol) else "ECHEC"
                if verbose:
                    print(f"{name:14s} {st['parts']:6d} {st['triangles']:7d}  "
                          f"{'✓' if wt else '✗':7s} {'✓' if vol else '✗':5s}  "
                          f"{[round(d, 3) for d in st['dims_m']]} [{flag}]")
                if not (wt and vol):
                    fails.append(name)
                tmp = os.path.join(tempfile.gettempdir(), f"smoke_{name}.glb")
                builder.scene().export(tmp)
            except Exception as e:
                if verbose:
                    print(f"{name:14s} EXCEPTION: {type(e).__name__}: {e}")
                fails.append(name)
        if verbose:
            print(f"\n→ {len(catalog()) - len(fails)}/{len(catalog())} recettes OK")
    finally:
        mk.set_quality(prev_q)
    return fails


def test_all_recipes_watertight():
    fails = run_smoke(verbose=False)
    assert not fails, f"Recettes non étanches ou en erreur : {fails}"


if __name__ == "__main__":
    bad = run_smoke(verbose=True)
    if bad:
        print("échecs :", ", ".join(bad))
        sys.exit(1)
