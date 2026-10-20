"""Test image→3D : roundtrip mask(mesh connu) → analyze → build → IoU.

Vérifie que la chaîne segmentation → contour/profil → reconstruction produit
une silhouette fidèle. Deux modes : revolve (vase) et extrude (épée).
"""
import json
import os
import sys
import tempfile

import numpy as np
import pytest
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import compare as cmp                        # noqa: E402
import img2mesh as i2m                       # noqa: E402
from recipes import get as get_recipe        # noqa: E402


def _ref_png(mesh, path, axes="xz"):
    mask = cmp.mesh_silhouette(mesh, axes=axes)
    im = Image.fromarray(np.where(mask, 0, 255).astype(np.uint8))
    im.save(path)
    return mask


def _roundtrip(name, mode, axes="xz", height=None, **kw):
    rec = get_recipe(name)
    m0 = rec["builder"](**rec["defaults"]).union_solid()
    h0 = float(m0.bounds[1][2] - m0.bounds[0][2])
    with tempfile.TemporaryDirectory() as td:
        ref = os.path.join(td, "ref.png")
        mask0 = _ref_png(m0, ref, axes=axes)
        an = i2m.analyze_file(ref, os.path.join(td, "an"))
        if mode == "revolve":
            m1 = i2m.build_revolve(an, height or h0)
        elif mode == "extrude":
            m1 = i2m.build_extrude(an, height or h0, depth=kw.get("depth", 0.1))
        else:
            m1 = i2m.build_loft(an, height or h0)
        mask1 = cmp.mesh_silhouette(m1, axes=axes)
        sc, _, _ = cmp.score_masks(mask0, mask1)
        print(f"[roundtrip {name}/{mode}] IoU={sc['iou']} "
              f"zones={sc['iou_zones']} asp ref={sc['ref_aspect']} "
              f"mesh={sc['mesh_aspect']}")
        assert sc["iou"] > 0.85, f"IoU trop bas: {sc['iou']}"
        return sc


@pytest.mark.parametrize("name,mode,kw", [
    ("vase", "revolve", {}),
    ("sword", "extrude", {"axes": "xz", "depth": 0.02}),
    ("bottle", "loft", {"depth": 0.07, "roundness": 0.5}),
])
def test_roundtrip(name, mode, kw):
    _roundtrip(name, mode, **kw)


if __name__ == "__main__":
    s1 = _roundtrip("vase", "revolve")
    s2 = _roundtrip("sword", "extrude", axes="xz", depth=0.02)
    s3 = _roundtrip("bottle", "loft", depth=0.07, roundness=0.5)
    print(json.dumps({"vase_revolve": s1["iou"], "sword_extrude": s2["iou"],
                      "bottle_loft": s3["iou"]}, indent=1))
    print("OK — roundtrip image→3D validé")
