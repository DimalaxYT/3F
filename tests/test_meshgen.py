#!/usr/bin/env python3
"""Test smoke meshgen : spec minimale -> mesh watertight + IoU > 0.35."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import meshgen  # noqa: E402

SPEC_MIN = {
    "name": "test_cube_arondi",
    "prompt": "cube arrondi de test",
    "size_m": 0.3,
    "res": 24,
    "upsample": 2,
    "smooth": 6,
    "budget_tris": 3000,
    "symmetry_x": True,
    "texture_size": 256,
    "palette": [
        {"id": "m", "name": "mat", "color": "#999999", "metallic": 0.1,
         "roughness": 0.6},
    ],
    "views": {
        "front": ["####", "####", "####", "####"],
        "side": ["##", "##", "##", "##"],
        "top": ["####", "####", "####", "####"],
    },
    "overlays": [],
}


def test_meshgen_smoke():
    with tempfile.TemporaryDirectory() as out:
        report = meshgen.generate(SPEC_MIN, out)
        v = report["validation"]
        assert v["watertight"], "mesh non watertight"
        assert v["triangles"] > 100
        assert not v["over_budget"]
        assert v["iou_mean"] > 0.35, f"IoU trop bas: {v['iou_mean']}"
        for f in ("glb", "stl"):
            assert os.path.exists(report["files"][f]["path"])
        print(f"OK smoke: {v['triangles']} tris, watertight, "
              f"IoU={v['iou_mean']}, {report['duration_s']}s")


def test_parse_views():
    mask, zones = meshgen.parse_view(["mmmm", "#..#"], ["m"], "front")
    assert mask.shape == (2, 4)
    assert mask[0].all()                 # 'mmmm' rempli
    assert list(mask[1]) == [True, False, False, True]
    assert zones[0, 0] == 0      # 'm' -> palette[0]
    assert zones[1, 0] == 0      # '#' -> primary = palette[0]
    assert zones[1, 1] == -1     # '.' -> vide
    # 's' absent de la palette -> SpecError attendu
    try:
        meshgen.parse_view([" s "], ["m"], "x")
        raise AssertionError("SpecError attendu pour lettre hors palette")
    except meshgen.SpecError:
        pass


if __name__ == "__main__":
    test_parse_views()
    test_meshgen_smoke()
    print("tests meshgen OK")
