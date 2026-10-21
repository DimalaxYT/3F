"""Test rapide de la recette motocross : build, stats, union solide, volume."""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.join(HERE, "..", "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from recipes import get as get_recipe     # noqa: E402


def main():
    t0 = time.time()
    recipe = get_recipe("motocross")
    builder = recipe["builder"](**recipe["defaults"])
    stats = builder.stats()
    bb = builder.bounds()
    print(f"pièces   : {stats['parts']}")
    print(f"triangles: {stats['triangles']}")
    print(f"verts    : {stats['vertices']}")
    print(f"dimensions (m): {stats['dims_m']}")
    print(f"bounds min: {bb[0].round(3)}  max: {bb[1].round(3)}")
    print(f"build    : {time.time() - t0:.2f}s")

    t1 = time.time()
    solid = builder.union_solid()
    print(f"union    : {time.time() - t1:.2f}s  "
          f"watertight={solid.is_watertight}  "
          f"volume={solid.volume * 1000:.1f} L  "
          f"tris={len(solid.faces)}")
    return 0 if solid.is_watertight and solid.volume > 0 else 1


def test_motocross_watertight_and_fast():
    t0 = time.time()
    recipe = get_recipe("motocross")
    builder = recipe["builder"](**recipe["defaults"])
    solid = builder.union_solid()
    elapsed = time.time() - t0
    assert solid.is_watertight
    assert solid.volume > 0.1
    assert elapsed < 5.0, f"motocross build+union trop lent : {elapsed:.2f}s"


if __name__ == "__main__":
    sys.exit(main())
