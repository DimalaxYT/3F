#!/usr/bin/env python3
"""Test smoke meshgen : spec minimale -> mesh watertight + IoU > 0.35."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import meshgen  # noqa: E402
import trimesh  # noqa: E402
import numpy as np  # noqa: E402

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


def test_fill_cavities():
    """_fill_closed_cavities comble une cavité fermée (erreur de dessin :
    coque en anneau) et laisse intacte une cavité ouverte (vase, bol)."""
    # coque fermée avec bulle interne (l'équivalent 3D d'une coque dessinée
    # en anneau dans les vues)
    occ = np.zeros((10, 10, 10), dtype=bool)
    occ[2:8, 2:8, 2:8] = True
    occ[4:6, 4:6, 4:6] = False          # poche fermée 2x2x2
    out = meshgen._fill_closed_cavities(occ, {})
    assert out.sum() == occ.sum() + 8, "poche fermée non comblée"
    assert out[4:6, 4:6, 4:6].all()
    # désactivé : rien ne change
    out_off = meshgen._fill_closed_cavities(occ, {"fill_cavities": False})
    assert out_off.sum() == occ.sum()
    # cavité ouverte (tube traversant vertical) : intouchée
    tube = np.ones((10, 10, 10), dtype=bool)
    tube[4:6, 4:6, :] = False           # ouvert en haut ET en bas
    out2 = meshgen._fill_closed_cavities(tube, {})
    assert out2.sum() == tube.sum(), "cavité ouverte modifiée"


def test_remove_debris():
    """Les îlots de < debris_min_faces faces sont supprimés ; le corps
    principal (>= 50 faces) reste intact."""
    body = trimesh.creation.icosphere(subdivisions=2, radius=1.0)  # 320 faces
    grit = trimesh.creation.box(extents=(0.02, 0.02, 0.02))        # 12 faces
    grit.apply_translation((3, 0, 0))    # îlot détaché
    mesh = trimesh.util.concatenate([body, grit])
    n_before = len(mesh.split(only_watertight=False))
    meshgen._remove_debris(mesh, {})
    n_after = len(mesh.split(only_watertight=False))
    assert n_after == n_before - 1, "îlot 12 faces non supprimé"
    assert mesh.metadata.get("debris_removed") == 1
    assert len(mesh.faces) == 320                 # le corps reste entier


if __name__ == "__main__":
    test_parse_views()
    test_fill_cavities()
    test_remove_debris()
    test_meshgen_smoke()
    print("tests meshgen OK")
