#!/usr/bin/env python3
"""
gates.py — Portes de qualité MESURABLES de `3d-forge` (v5.2).

Les gates Roblox/UE5/print étaient déjà *écrits* dans `tests/test_v5_game_ready.py`
mais invisibles pour l'agent et la CI E2E. Ce module les expose en CLI :

    python3 scripts/gates.py out/<nom> [--target hero|ugc|print] [--json]

→ écrit `out/<nom>/gates.json` (1 ligne par gate : id / libellé / pass / valeur /
  attendu), imprime un résumé lisible et sort avec un code non nul si un gate
  échoue. `turbo_forge.py` l'appelle automatiquement en fin de run.

Cibles (`--target`) — plafonds DOCUMENTÉS par cible, le code est la source de vérité :
  * `hero`  : asset temps réel standard   — <= 9 800 tris/MeshPart (budget de perf ;
              le plafond moteur Roblox actuel est 20 000 tris/mesh), textures <= 1024².
  * `ugc`   : accessoire UGC rigide Roblox — <= 4 000 tris (modération UGC),
              textures <= 1024².
  * `print` : impression 3D — STL watertight + volume > 0 obligatoire, tris libres.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

ROBLOX_STUDS_PER_METER = 25.0 / 7.0  # 1 Stud = 0.28 m (spec Roblox 25:7)
ROBLOX_MAX_TEX_SIZE = 1024
ROBLOX_ENGINE_MESH_CAP = 20_000  # plafond moteur Roblox (Creator Store)
ROBLOX_UGC_RIGID_CAP = 4_000  # modération UGC accessoire rigide

TARGETS = {
    "hero": {"max_part_tris": 9_800, "max_tex": ROBLOX_MAX_TEX_SIZE, "require_stl": False},
    "ugc": {"max_part_tris": ROBLOX_UGC_RIGID_CAP, "max_tex": ROBLOX_MAX_TEX_SIZE, "require_stl": False},
    "print": {"max_part_tris": ROBLOX_ENGINE_MESH_CAP, "max_tex": ROBLOX_MAX_TEX_SIZE, "require_stl": True},
}


def _glb_json(path: Path) -> dict | None:
    """Lit le chunk JSON d'un `.glb` sans charger les binaries (rapide, sans trimesh)."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) < 20 or raw[:4] != b"glTF":
        return None
    j_len, j_type = struct.unpack_from("<II", raw, 12)
    if j_type != 0x4E4F534A:
        return None
    try:
        return json.loads(raw[20:20 + j_len].decode("utf-8"))
    except Exception:
        return None


def _png_size(path: Path) -> tuple[int, int] | None:
    try:
        raw = path.read_bytes()[:33]
    except OSError:
        return None
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", raw[16:24])
    return int(w), int(h)


class GateList:
    def __init__(self) -> None:
        self.gates: list[dict] = []

    def add(self, gid: str, label: str, ok: bool, value, expected) -> None:
        self.gates.append({
            "id": gid, "label": label, "pass": bool(ok),
            "value": value, "expected": expected,
        })
    @property
    def all_pass(self) -> bool:
        return all(g["pass"] for g in self.gates)

    def to_dict(self, target: str, out_dir: str) -> dict:
        return {
            "target": target,
            "out_dir": str(out_dir),
            "all_pass": self.all_pass,
            "n_pass": sum(1 for g in self.gates if g["pass"]),
            "n_total": len(self.gates),
            "gates": self.gates,
        }


def luau_issues(lua: str, man: dict) -> list[str]:
    """Invariants structurels de `setup_<Name>.lua` (pas de compilateur Luau en
    sandbox : on vérifie ce qui peut casser silencieusement dans la Command Bar)."""
    import re as _re
    issues = []
    # En Lua, `for … do` / `while … do` ne ferment qu'UN seul `end` : le `do`
    # porté par la ligne for/while ne compte pas comme bloc supplémentaire.
    code_lines = [l for l in lua.splitlines() if not l.strip().startswith("--")]
    bare_do = 0
    for l in code_lines:
        n_fw = len(_re.findall(r"\b(for|while)\b", l))
        n_do = len(_re.findall(r"\bdo\b", l))
        bare_do += max(0, n_do - n_fw)
    code = "\n".join(code_lines)
    opens = len(_re.findall(r"\b(if|function|for|while)\b", code)) + bare_do
    ends = len(_re.findall(r"\bend\b", code))
    if opens != ends:
        issues.append(f"blocs ouverts ({opens}) != end ({ends})")
    rbx = man.get("engine_exports", {}).get("roblox", {}) or {}
    for n in rbx.get("neon_parts", []):
        if f"'{n}'" not in lua and f'"{n}"' not in lua:
            issues.append(f"pièce Neon {n} absente de NEON_COLORS")
    if rbx.get("neon_parts") and "Enum.Material.Neon" not in lua:
        issues.append("Enum.Material.Neon absent")
    for s in (man.get("sockets") or {}):
        key = s.replace("SOCKET_", "") + "Attachment"
        if key not in lua:
            issues.append(f"socket {s} absent de SOCKETS_WORLD_OFFSET")
    return issues


def _normals_cross_ok(rbx_n: Path, ue_n: Path) -> tuple[bool, str]:
    """Cohérence DirectX `-Y` : `G_unreal == 255 - G_roblox` (map Roblox = OpenGL `+Y`)."""
    try:
        import numpy as np
        from PIL import Image
        a = np.asarray(Image.open(rbx_n).convert("RGB"), dtype=np.int16)
        im_b = Image.open(ue_n).convert("RGB")
        if im_b.size != (a.shape[1], a.shape[0]):
            im_b = im_b.resize((a.shape[1], a.shape[0]))
        b = np.asarray(im_b, dtype=np.int16)
        bad = int((np.abs(a[..., 1] + b[..., 1] - 255) > 1).sum())
        return bad == 0, f"{bad} pixel(s) G incohérent(s)"
    except Exception as exc:
        return False, f"erreur : {exc}"


def _lod_silhouette(man: dict, lod: str = "LOD2", tol_mean_pct: float = 1.0,
                    tol_p95_pct: float = 3.0) -> tuple[bool, str]:
    """Écart géométrique LOD0↔LOD2 (proximity trimesh) : une décimation ne doit
    pas détruire la silhouette — mesurable sans lire une seule image.
    Seuils calibrés sur sci_fi_crate sain : moy 0.27 %, p95 1.6 %."""
    import numpy as np
    import trimesh
    g0 = max(trimesh.load(man["lods"]["LOD0"]["path"]).geometry.values(), key=lambda g: len(g.faces))
    g2 = max(trimesh.load(man["lods"][lod]["path"]).geometry.values(), key=lambda g: len(g.faces))
    dists, _faces = trimesh.proximity.ProximityQuery(g0).vertex(np.asarray(g2.vertices))
    d = np.abs(np.asarray(dists, dtype=np.float64))
    diag = float(np.linalg.norm(g0.extents)) + 1e-9
    p95 = 100.0 * float(np.percentile(d, 95)) / diag
    mean = 100.0 * float(np.mean(d)) / diag
    ok = mean <= tol_mean_pct and p95 <= tol_p95_pct
    return ok, (f"moy {mean:.2f} % (<= {tol_mean_pct} %) / p95 {p95:.2f} % "
                f"(<= {tol_p95_pct} %) de la diagonale")


def _uv_fill(man: dict) -> tuple[bool, str]:
    """Couverture d'atlas UV du LOD0 (densité texel) + bornes [0, 1]."""
    import numpy as np
    import trimesh
    from PIL import Image, ImageDraw
    # v5.7 — on mesurait le plus gros mesh, qui peut être une pièce émissive
    # sans UV (abat-jour de la lampe) : la gate levait « invalid index to scalar
    # variable ». On prend le mesh TEXTURÉ le plus lourd, celui que l'atlas décrit.
    _geoms = list(trimesh.load(man["lods"]["LOD0"]["path"]).geometry.values())
    _with_uv = [g for g in _geoms
                if getattr(g.visual, "uv", None) is not None and len(np.asarray(g.visual.uv))]
    if not _with_uv:
        return False, "pas d'UV"
    g0 = max(_with_uv, key=lambda g: len(g.faces))
    uv = np.asarray(g0.visual.uv, dtype=np.float64)
    if uv.size == 0:
        return False, "pas d'UV"
    oob = float(np.mean((uv < -0.001) | (uv > 1.001)))
    S = 256
    im = Image.new("L", (S, S), 0)
    dr = ImageDraw.Draw(im)
    pts = np.clip(uv, 0.0, 1.0) * (S - 1)
    for tri in np.asarray(g0.faces):
        dr.polygon([tuple(pts[tri[0]]), tuple(pts[tri[1]]), tuple(pts[tri[2]])], fill=255)
    cov = float(np.mean(np.asarray(im) > 0))
    return (cov >= 0.5 and oob <= 0.001), f"couverture atlas {cov:.2f} (>= 0.5), hors [0,1] {oob:.4f}"


def _ucx_budget(ue_glb: Path, max_hulls: int = 6, max_tris: int = 64) -> tuple[bool, str]:
    g = _glb_json(ue_glb) or {}
    meshes = g.get("meshes", [])
    accs = g.get("accessors", [])
    hulls = []
    for n in g.get("nodes", []):
        if n.get("name", "").startswith("UCX_"):
            tris = 0
            mi = n.get("mesh")
            if mi is not None and mi < len(meshes):
                for pr in meshes[mi].get("primitives", []):
                    ai = pr.get("indices")
                    if ai is not None and ai < len(accs):
                        tris += accs[ai].get("count", 0) // 3
            hulls.append(tris)
    ok = 0 < len(hulls) <= max_hulls and all(t <= max_tris for t in hulls)
    return ok, (f"{len(hulls)} hulls (<= {max_hulls}), max "
                f"{max(hulls) if hulls else 0} tris/hull (<= {max_tris})")



def _texture_content(out_p: Path, name: str) -> tuple[bool, str]:
    """Détecte les bakes silencieusement ratés : cartes plates (noir/blanc uni) et
    normal map dégénérée. Mesuré sur des cas sains : BC std ≈ 48-59, ORM 30-84,
    N std RG ≈ 27-40 avec moyenne B ≈ 240-246."""
    import numpy as np
    from PIL import Image
    details = []
    for suf in ("BC", "ORM"):
        fp = out_p / "unreal" / f"T_{name}_{suf}.png"
        if not fp.is_file():
            return False, f"T_{name}_{suf}.png absent"
        a = np.asarray(Image.open(fp).convert("RGB"), dtype=np.float32)
        std = float(a.reshape(-1, 3).std(axis=0).max())
        if std < 3.0:
            return False, f"{suf} plate (std max {std:.1f} < 3) — bake échoué ?"
        details.append(f"{suf} std {std:.0f}")
    fn = out_p / "unreal" / f"T_{name}_N.png"
    if fn.is_file():
        a = np.asarray(Image.open(fn).convert("RGB"), dtype=np.float32)
        std_rg = float(a[..., :2].reshape(-1, 2).std(axis=0).min())
        mean_b = float(a[..., 2].mean())
        if std_rg < 2.0 or mean_b < 180.0:
            return False, (f"N dégénérée : std RG {std_rg:.1f} (>= 2), "
                           f"moyenne B {mean_b:.0f} (>= 180)")
        details.append(f"N stdRG {std_rg:.0f} / B {mean_b:.0f}")
    return True, ", ".join(details)


def _emissive_ok(glb: Path | None, man: dict) -> tuple[bool, str]:
    """Une pièce `neon` déclarée doit produire un matériau émissif dans le GLB
    (sinon le néon sera terne dans Studio malgré le script Luau)."""
    neon = (man.get("engine_exports", {}).get("roblox", {}) or {}).get("neon_parts") or []
    if not neon:
        return True, "aucune pièce Neon déclarée"
    if not glb or not Path(glb).is_file():
        return False, "GLB Roblox absent"
    g = _glb_json(Path(glb)) or {}
    emis = [m.get("name", "?") for m in g.get("materials", [])
            if max(m.get("emissiveFactor") or [0.0]) > 0.3]
    return bool(emis), f"{len(emis)} matériau(x) émissif(s) pour {len(neon)} pièce(s) Neon"



def _uv_overlap(man: dict, max_ratio: float = 1.05) -> tuple[bool, str]:
    """Détecte un atlas UV qui superpose des îlots (bavage de texture).

    Métrique insensible aux arêtes partagées : aire totale des triangles en
    espace UV / aire réellement couverte. Sans chevauchement, le ratio vaut
    <= 1 (la rastérisation perd les triangles fins). Mesuré sain : 0.91-0.98 ;
    un atlas dupliqué monte au-delà de 1.2.
    """
    import numpy as np
    import trimesh
    from PIL import Image, ImageDraw
    _geoms = list(trimesh.load(man["lods"]["LOD0"]["path"]).geometry.values())
    _with_uv = [g for g in _geoms
                if getattr(g.visual, "uv", None) is not None and len(np.asarray(g.visual.uv))]
    if not _with_uv:
        return False, "pas d'UV"
    g0 = max(_with_uv, key=lambda g: len(g.faces))
    uv = np.asarray(g0.visual.uv, dtype=np.float64)
    if uv.size == 0:
        return False, "pas d'UV"
    f = np.asarray(g0.faces)
    S = 512
    p = np.clip(uv, 0, 1) * (S - 1)
    area = 0.5 * np.abs(
        (p[f[:, 1], 0] - p[f[:, 0], 0]) * (p[f[:, 2], 1] - p[f[:, 0], 1])
        - (p[f[:, 2], 0] - p[f[:, 0], 0]) * (p[f[:, 1], 1] - p[f[:, 0], 1])
    )
    im = Image.new("L", (S, S), 0)
    dr = ImageDraw.Draw(im)
    for tri in f:
        dr.polygon([tuple(p[tri[0]]), tuple(p[tri[1]]), tuple(p[tri[2]])], fill=255)
    cov = int((np.asarray(im) > 0).sum())
    ratio = float(area.sum()) / max(cov, 1)
    return ratio <= max_ratio, f"ratio aire UV/couverture {ratio:.3f} (<= {max_ratio})"



def _albedo_design(out_p: Path, name: str) -> tuple[bool, str]:
    """Qualité de DESIGN de l'albédo (et pas seulement « pas plate »).

    Trois défauts mesurés sur des rendus jugés ternes, encodés ici :
      - saturation écrasée : l'objet se lit gris (les accents colorés comptent) ;
      - contraste local faible : aspect plastique uniforme ;
      - budget de blancs : une usure d'arêtes mal masquée « neige » la surface
        (mesuré avant correction : 6.3 % de pixels > 0.7 sur la caisse).
    Valeurs saines mesurées : sat 0.25-0.27, std 0.19-0.30, blancs 0-8.4 %.
    """
    import numpy as np
    from PIL import Image
    fp = out_p / "unreal" / f"T_{name}_BC.png"
    if not fp.is_file():
        return False, "ColorMap absente"
    im = Image.open(fp).convert("RGB")
    a = np.asarray(im, dtype=np.float32) / 255.0
    sat = float(np.asarray(im.convert("HSV"), dtype=np.float32)[..., 1].mean() / 255.0)
    std = float(a.reshape(-1, 3).std(axis=0).mean())
    lum = a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    whites = float((lum > 0.85).mean())
    # v5.7 — la version v5.6 jugeait la saturation et le contraste absolus : elle
    # rejetait une porcelaine blanche (sat 0.02, contraste 0.015) et un aplat
    # émaillé riche, qui sont des designs VALIDES. Le défaut réel mesuré sur le
    # pion d'échecs était autre : un albédo à 0.94 de luminance médiane, donc
    # C RAMÉ — au-delà, grain et variations étaient clippés à 1.0 (headroom
    # perdu) et la lumière n'avait plus de place pour modeler la surface.
    # On vérifie donc la RÉSERVE de dynamique, pas le style.
    p99 = float(np.percentile(lum, 99))
    clipped = float((lum > 0.995).mean())
    details = (f"p99 {p99:.2f} (<= 0.92) | cramés {clipped * 100:.1f} % (<= 2 %) | "
               f"sat {sat:.2f} / contraste {std:.3f}")
    ok = (clipped <= 0.02) and (p99 <= 0.92)
    return ok, details



def _shading_modeled(man: dict) -> tuple[bool, str]:
    """Modelé du rendu : la lumière doit réellement sculpter l'objet.

    Trois défauts vécus, tous invisibles sur l'albédo seul :
      - pion d'échecs mesuré à une luminance médiane de 0.945 avec une
        dynamique de 0.09 : surface cramée, aucune forme lisible ;
      - `I = [key, fill, rim]` construit puis jamais utilisé, les radiances
        restant à 3.05 / 2.15 / 1.75 (remplissage à 70 % de la clé) ;
      - exposition globale qui cramait les albédos clairs.
    On rend la vue de face du LOD0 et on mesure la dynamique de luminance
    p95-p05 SUR LA SILHOUETTE (jamais sur le cyclorama).
    """
    import numpy as np
    import trimesh
    from renderer import render_view
    g0_path = man["lods"]["LOD0"]["path"]
    sc = trimesh.load(g0_path, process=False, force="scene")
    # Le verre est rendu par une passe dédiée hors z-buffer : sur un asset 100 %
    # verre la silhouette serait vide. On juge donc le modèle DIFFUS (opacité
    # forcée) — c'est lui qu'on veut voir sculpté par la lumière.
    for gg in sc.geometry.values():
        mm = getattr(gg.visual, "material", None)
        if mm is not None:
            # l'opacité vient de `baseColorFactor[3]` (alpha 0.30 sur le verre),
            # pas seulement d'`alphaMode` : on force les deux.
            bcf = getattr(mm, "baseColorFactor", None)
            if bcf is not None and len(bcf) > 3 and (bcf[3] > 1.0 and bcf[3] < 255.0):
                bcf[3] = 255
            mm.alphaMode = "OPAQUE"
    img, mask = render_view(sc, size=320, ssaa=1, post=False, return_mask=True)
    a = np.asarray(img, dtype=np.float32) / 255.0
    mk = np.asarray(mask) > 128
    if mk.sum() < 200:
        return False, "silhouette vide"
    lum = (a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32))[mk]
    p05, p95 = float(np.percentile(lum, 5)), float(np.percentile(lum, 95))
    dyn = p95 - p05
    med = float(np.median(lum))
    details = f"dynamique {dyn:.3f} (>= 0.12) | médiane {med:.2f} (<= 0.90)"
    return (dyn >= 0.12 and med <= 0.90), details


def check_package(out_dir: str | Path, target: str = "hero") -> dict:
    """Évalue toutes les gates d'un dossier produit par `turbo_forge.py`/`game_ready.py`."""
    out_p = Path(out_dir)
    cfg = TARGETS[target]
    g = GateList()

    man_p = out_p / "game_manifest.json"
    if not man_p.is_file():
        g.add("manifest", "game_manifest.json présent", False, str(man_p), "fichier existant")
        return g.to_dict(target, out_p)
    man = json.loads(man_p.read_text(encoding="utf-8"))
    g.add("manifest", "game_manifest.json présent", True, str(man_p), "fichier existant")

    name = man.get("asset_name", out_p.name)
    lods = man.get("lods", {})

    # --- budget triangles par MeshPart / par cible -------------------------
    rbx = man.get("engine_exports", {}).get("roblox", {})
    max_part = int(rbx.get("max_part_tris", lods.get("LOD0", {}).get("tris", 0)))
    g.add("tris_part", f"tris/MeshPart <= {cfg['max_part_tris']} (cible {target})",
          0 < max_part <= cfg["max_part_tris"], max_part, f"<= {cfg['max_part_tris']}")
    g.add("tris_engine_cap", f"tris/MeshPart <= plafond moteur Roblox {ROBLOX_ENGINE_MESH_CAP}",
          max_part <= ROBLOX_ENGINE_MESH_CAP, max_part, f"<= {ROBLOX_ENGINE_MESH_CAP}")

    # --- chaîne LOD monotone ------------------------------------------------
    t0 = int(lods.get("LOD0", {}).get("tris", 0))
    t1 = int(lods.get("LOD1", {}).get("tris", 0))
    t2 = int(lods.get("LOD2", {}).get("tris", 0))
    g.add("lod_chain", "LOD0 > LOD1 > LOD2 > 50 tris", t0 > t1 > t2 > 50,
          f"{t0}/{t1}/{t2}", "décroissant")

    # --- pack Roblox : PNG pur, textures <= 1024², Studs raisonnables --------
    rbx_glb = rbx.get("studio_ready_glb_png")
    if rbx_glb and Path(rbx_glb).is_file():
        gj = _glb_json(Path(rbx_glb)) or {}
        mimes = [im.get("mimeType") for im in gj.get("images", [])]
        g.add("roblox_png", "roblox/*.glb = PNG pur (zéro EXT_texture_webp)",
              bool(mimes) and all(m == "image/png" for m in mimes)
              and "EXT_texture_webp" not in (gj.get("extensionsUsed") or []),
              sorted(set(mimes)), "['image/png']")
        tex_ok = True
        dims = []
        sa = rbx.get("surface_appearance", {})
        for p in sa.values():
            d = _png_size(Path(p)) if isinstance(p, str) else None
            if d:
                dims.append(d)
                if d[0] > cfg["max_tex"] or d[1] > cfg["max_tex"]:
                    tex_ok = False
        g.add("roblox_tex", f"textures SurfaceAppearance <= {cfg['max_tex']}²",
              tex_ok and bool(dims), dims, f"<= {cfg['max_tex']}x{cfg['max_tex']}")
        studs = rbx.get("size_studs_xyz") or [0, 0, 0]
        g.add("roblox_studs", "dims Studs dans [0.1, 2048] par axe",
              all(0.1 <= s <= 2048 for s in studs), [round(s, 2) for s in studs], "[0.1, 2048]")
        lua = rbx.get("luau_setup_script")
        g.add("roblox_lua", "setup_<Name>.lua présent et non vide",
              bool(lua) and Path(lua).is_file() and Path(lua).stat().st_size > 200,
              lua, "fichier > 200 o")
    else:
        g.add("roblox_png", "pack roblox/ présent", False, rbx_glb, "roblox/<name>_roblox.glb")

    # --- pack Unreal ---------------------------------------------------------
    ue = man.get("engine_exports", {}).get("unreal", {})
    ue_glb = ue.get("static_mesh_with_ucx") or ue.get("static_mesh_glb")
    if ue_glb is None:
        cand = list((out_p / "unreal").glob("SM_*.glb")) if (out_p / "unreal").is_dir() else []
        ue_glb = str(cand[0]) if cand else None
    if ue_glb and Path(ue_glb).is_file():
        gj = _glb_json(Path(ue_glb)) or {}
        nodes = [n.get("name", "") for n in gj.get("nodes", [])]
        g.add("ue_ucx", "colliders convexes UCX_SM_* présents",
              any(n.startswith("UCX_") for n in nodes),
              sum(1 for n in nodes if n.startswith("UCX_")), ">= 1")
        bc = ue.get("base_color")
        orm = ue.get("orm_packed") or ue.get("orm")
        nrm = ue.get("normal_directx_neg_y") or ue.get("normal_dx")
        g.add("ue_maps", "T_*_BC / T_*_ORM / T_*_N (DirectX -Y) présents",
              all(p and Path(p).is_file() for p in (bc, orm, nrm)),
              [bool(bc), bool(orm), bool(nrm)], "[True, True, True]")
    else:
        g.add("ue_ucx", "pack unreal/ présent", False, ue_glb, "unreal/SM_<name>.glb")

    # --- STL impression ------------------------------------------------------
    stl = man.get("printable_stl")
    if stl and Path(stl).is_file():
        wt = man.get("stl_watertight")
        vol = None
        try:
            import trimesh
            # process=True (défaut) : fusion des sommets coïncidents, comme le fait
            # un slicer — c'est la sémantique « étanche » qui compte pour l'impression.
            m = trimesh.load(stl)
            wt = bool(m.is_watertight)
            vol = float(m.volume)
        except Exception:
            pass
        g.add("stl_watertight", "STL 100 % watertight", bool(wt), wt, True)
        g.add("stl_volume", "STL volume strictement positif", bool(vol and vol > 0),
              round(vol, 6) if vol is not None else None, "> 0")
    elif cfg["require_stl"]:
        g.add("stl_watertight", "STL présent (cible print)", False, stl, "<name>.stl")

    # --- design de l'albédo (v5.7) -------------------------------------------
    try:
        ok, val = _albedo_design(out_p, name)
        g.add("albedo_design", "albédo : saturation, contraste et blancs maîtrisés",
              ok, val, "p99 <= 0.92 ; cramés <= 2 %")
    except Exception as exc:
        g.add("albedo_design", "albédo mesurable", False, str(exc), "mesure ok")

    # --- modelé du rendu (v5.7) ---------------------------------------------
    try:
        ok, val = _shading_modeled(man)
        g.add("shading_modeled", "rendu modelé : la lumière sculpte le volume",
              ok, val, "dynamique >= 0.12, médiane <= 0.90")
    except Exception as exc:
        g.add("shading_modeled", "rendu modelable", False, str(exc), "mesure ok")

    # --- contenu des textures & émission néon (v5.4) -------------------------
    try:
        ok, val = _texture_content(out_p, name)
        g.add("texture_content", "cartes PBR non plates + normal map valide", ok, val,
              "std >= 3 / N stdRG >= 2, B >= 180")
    except Exception as exc:
        g.add("texture_content", "cartes PBR mesurables", False, str(exc), "mesure ok")

    try:
        ok, val = _emissive_ok(Path(rbx_glb) if rbx_glb else None, man)
        g.add("emissive", "pièce Neon => matériau émissif dans le GLB", ok, val,
              ">= 1 matériau émissif")
    except Exception as exc:
        g.add("emissive", "émission mesurable", False, str(exc), "mesure ok")

    # --- QA visuelle ---------------------------------------------------------
    qa = man.get("qa_sheet")
    g.add("qa_sheet", "qa_game_sheet.png présent", bool(qa) and Path(qa).is_file(), qa, "png")

    # --- gates de comportement (v5.3) ----------------------------------------
    # animations : des joints déclarés doivent exporter gltf.animations
    if man.get("joints"):
        gj = _glb_json(Path(lods["LOD0"]["path"])) if lods.get("LOD0") else None
        names = [a.get("name") for a in (gj or {}).get("animations", [])]
        g.add("animations", "gltf.animations (Idle_Action) présent si joints déclarés",
              "Idle_Action" in names, names, "contient Idle_Action")

    # normales : cohérence pixel DirectX -Y (Unreal) vs OpenGL +Y (Roblox)
    rbx_n = out_p / "roblox" / f"T_{name}_NormalMap.png"
    ue_n = ue.get("normal_directx_neg_y") or ue.get("normal_dx") if ue else None
    if rbx_n.is_file() and ue_n and Path(ue_n).is_file():
        ok, val = _normals_cross_ok(rbx_n, Path(ue_n))
        g.add("normal_dx_vs_gl", "G_Unreal == 255 - G_Roblox (DirectX -Y exact)", ok, val, "0 pixel")

    # silhouette LOD2 vs LOD0
    if lods.get("LOD0") and lods.get("LOD2"):
        try:
            ok, val = _lod_silhouette(man, "LOD2")
            g.add("lod_silhouette", "écart LOD0↔LOD2 : moy <= 1 % / p95 <= 3 % diagonale",
                  ok, val, "moy <= 1 % / p95 <= 3 %")
        except Exception as exc:
            g.add("lod_silhouette", "écart LOD0↔LOD2 mesurable", False, str(exc), "mesure ok")

    # silhouette LOD1 (LOD intermédiaire cassé = popping visible en jeu)
    if lods.get("LOD0") and lods.get("LOD1"):
        try:
            # Mêmes bornes que LOD2 : un LOD1 peut légitimement dévier un peu plus
            # qu'un LOD2 (bake d'atlas différent) ; cette gate attrape un LOD1 cassé.
            ok, val = _lod_silhouette(man, "LOD1")
            g.add("lod1_silhouette", "écart LOD0↔LOD1 : moy <= 1 % / p95 <= 3 %",
                  ok, val, "moy <= 1 % / p95 <= 3 %")
        except Exception as exc:
            g.add("lod1_silhouette", "écart LOD0↔LOD1 mesurable", False, str(exc), "mesure ok")

    # densité texel / bornes UV
    if lods.get("LOD0"):
        try:
            ok, val = _uv_fill(man)
            g.add("uv_fill", "couverture d'atlas UV >= 0.5 et UV dans [0, 1]", ok, val, ">= 0.5")
        except Exception as exc:
            g.add("uv_fill", "UV mesurables", False, str(exc), "mesure ok")

    # chevauchement d'îlots UV (bavage de texture)
    if lods.get("LOD0"):
        try:
            ok, val = _uv_overlap(man)
            g.add("uv_overlap", "îlots UV sans superposition (aire/couverture <= 1.05)",
                  ok, val, "<= 1.05")
        except Exception as exc:
            g.add("uv_overlap", "chevauchement UV mesurable", False, str(exc), "mesure ok")

    # structure du script Luau
    lua_p = rbx.get("luau_setup_script")
    if lua_p and Path(lua_p).is_file():
        issues = luau_issues(Path(lua_p).read_text(encoding="utf-8"), man)
        g.add("luau_structure", "setup_<Name>.lua : blocs balancés + Neon + sockets",
              not issues, issues or "ok", "0 issue")

    # budget colliders convexes
    if ue_glb and Path(ue_glb).is_file():
        ok, val = _ucx_budget(Path(ue_glb))
        g.add("ucx_budget", "UCX : <= 6 hulls et <= 64 tris/hull", ok, val, "<= 6 hulls / 64 tris")

    return g.to_dict(target, out_p)


def write_outputs(out_dir: str | Path, result: dict, summary_md: bool = True) -> Path:
    out_p = Path(out_dir)
    gp = out_p / "gates.json"
    gp.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if summary_md:
        man_p = out_p / "game_manifest.json"
        man = json.loads(man_p.read_text(encoding="utf-8")) if man_p.is_file() else {}
        lines = [f"# QA summary — {man.get('asset_name', out_p.name)}", ""]
        lines.append(f"Cible : **{result['target']}** | gates : "
                     f"**{result['n_pass']}/{result['n_total']} OK** "
                     f"({'LIVRABLE' if result['all_pass'] else 'NON LIVRABLE'})")
        lines.append("")
        lines.append("| gate | résultat | valeur | attendu |")
        lines.append("|---|---|---|---|")
        for gt in result["gates"]:
            lines.append(f"| {gt['label']} | {'✅' if gt['pass'] else '❌'} "
                         f"| {gt['value']} | {gt['expected']} |")
        lods = man.get("lods", {})
        if lods:
            lines.append("")
            lines.append(f"- LOD0 {lods.get('LOD0', {}).get('tris')} tris | "
                         f"LOD1 {lods.get('LOD1', {}).get('tris')} | "
                         f"LOD2 {lods.get('LOD2', {}).get('tris')} | "
                         f"draw calls {man.get('draw_calls_before')} -> {man.get('draw_calls_after')}")
        rbx = man.get("engine_exports", {}).get("roblox", {})
        if rbx:
            studs = rbx.get("size_studs_xyz") or []
            lines.append(f"- Roblox : {rbx.get('max_part_tris')} tris/part max, "
                         f"{' x '.join(f'{s:.2f}' for s in studs)} Studs, "
                         f"{len(rbx.get('neon_parts', []))} pièce(s) Neon")
        lines.append(f"- STL : `{man.get('printable_stl', '-')}` "
                     f"(watertight={man.get('stl_watertight')})")
        lines.append(f"- Durée pipeline : {man.get('turbo_total_s', man.get('duration_s', '?'))} s")
        (out_p / "qa_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return gp


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir", help="dossier de sortie turbo_forge/game_ready")
    ap.add_argument("--target", choices=sorted(TARGETS), default="hero")
    ap.add_argument("--json", action="store_true", help="imprime gates.json complet")
    ap.add_argument("--no-summary", action="store_true", help="n'écrit pas qa_summary.md")
    args = ap.parse_args(argv)

    res = check_package(args.out_dir, args.target)
    write_outputs(args.out_dir, res, summary_md=not args.no_summary)
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        for gt in res["gates"]:
            mark = "OK  " if gt["pass"] else "FAIL"
            print(f"  [{mark}] {gt['label']} : {gt['value']} (attendu {gt['expected']})")
        print(f"=> gates {res['n_pass']}/{res['n_total']} "
              f"({'LIVRABLE' if res['all_pass'] else 'NON LIVRABLE'}) "
              f"-> {Path(args.out_dir) / 'gates.json'}")
    return 0 if res["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
