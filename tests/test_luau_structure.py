"""Invariants structurels du script Luau généré (`setup_<Name>.lua`).

Pas de compilateur Luau dans la sandbox : on vérifie ce qui casse silencieusement
dans la Command Bar Roblox Studio (blocs non balancés, pièce Neon oubliée,
socket absent de la table d'offsets). Réutilise `gates.luau_issues` pour que le
test et la gate partagent exactement la même définition.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import gates as gt  # noqa: E402
import game_ready as gr  # noqa: E402
from generate import get_recipe  # noqa: E402


def test_generated_luau_is_structurally_complete(tmp_path: Path):
    builder = get_recipe("sci_fi_crate")["builder"]()
    man = gr.export_game_package(
        builder, out_dir=tmp_path, name="sci_fi_crate",
        engine="roblox_unreal", lod0_tris=2400, tex_size=512,
    )
    lua_p = man["engine_exports"]["roblox"]["luau_setup_script"]
    lua = Path(lua_p).read_text(encoding="utf-8")

    issues = gt.luau_issues(lua, man)
    assert issues == [], f"setup lua invalide : {issues}"

    # toutes les pièces Neon du manifest doivent être configurées
    for neon in man["engine_exports"]["roblox"]["neon_parts"]:
        assert neon in lua
    # et chaque socket déclaré doit avoir son offset monde
    for sock in man["sockets"]:
        assert sock.replace("SOCKET_", "") + "Attachment" in lua
    # les articulations déclarées doivent produire une animation exportable
    assert man.get("joints"), "sci_fi_crate déclare un joint `lid`"
    import json
    import struct
    raw = Path(man["lods"]["LOD0"]["path"]).read_bytes()
    j_len, _ = struct.unpack_from("<II", raw, 12)
    gltf = json.loads(raw[20:20 + j_len].decode("utf-8"))
    assert any(a.get("name") == "Idle_Action" for a in gltf.get("animations", []))
