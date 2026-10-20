"""Test de fumée : construit chaque recette (qualité réduite), vérifie étanchéité
du solide fusionné + export GLB. Exécuter depuis scripts/ ou racine du skill."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # racine skill
sys.path.insert(0, os.path.join(HERE, "scripts"))

import meshkit as mk          # noqa: E402
from recipes import catalog, get as get_recipe   # noqa: E402

mk.set_quality(0.5)

fails = []
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
        print(f"{name:14s} {st['parts']:6d} {st['triangles']:7d}  "
              f"{'✓' if wt else '✗':7s} {'✓' if vol else '✗':5s}  "
              f"{[round(d, 3) for d in st['dims_m']]} [{flag}]")
        if not (wt and vol):
            fails.append(name)
        # export GLB de contrôle
        tmp = os.path.join(tempfile.gettempdir(), f"smoke_{name}.glb")
        builder.scene().export(tmp)
    except Exception as e:
        print(f"{name:14s} EXCEPTION: {type(e).__name__}: {e}")
        fails.append(name)

print()
print(f"→ {len(catalog()) - len(fails)}/{len(catalog())} recettes OK")
if fails:
    print("échecs :", ", ".join(fails))
    sys.exit(1)
