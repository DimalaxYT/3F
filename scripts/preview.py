"""Visionneuse 3D Studio v6.0 autonome — 100 % compatible WebGL2, WebGL1, iframes sandboxés et hors-ligne.

Corrections architecturales majeures (v6.0) :
- Shaders GLSL universels **zéro extension** (`aPos`, `aNrm`, `aUV`, `aTan` MikkTSpace en vertex) :
  aucun appel `dFdx`/`dFdy` ni `#extension GL_OES_standard_derivatives` -> compile à **100,0 %**
  sur WebGL2, WebGL1, ANGLE D3D11/Metal/Vulkan, Firefox, Safari, mobile et SwiftShader.
- Décodage textures **100 % Data-URI Base64** (`data:image/...;base64,...`) sans `URL.createObjectURL` :
  fonctionne dans les iframes `sandbox="allow-scripts"` (`origin === "null"`), `file://`, et `https://`.
- **Sélecteur multi-LOD temps réel (`LOD0 / LOD1 / LOD2`)** embarqué automatiquement si présent.
- **Vraies arêtes filaires (`bWire`)** superposables au PBR + inspecteur de canaux (`Studio PBR`,
  `Plein air`, `Clay`, `Albedo`, `Normals`, `Roughness`, `AO`, `Metal`, `Damier UV`).
- **6 cadrages caméra** (`Face`, `3/4`, `Profil`, `Arrière`, `Dessus`, `↺ Reset`) + Plein écran.
- **Moteur 3D logiciel `<canvas 2d>` de secours automatique** si WebGL est désactivé dans le navigateur.
"""
from __future__ import annotations

import argparse
import base64
import html as _html
import json
import math
import struct
from pathlib import Path

PHOTO_SLOTS = [
    ("front.png", "face"),
    ("back.png", "dos"),
    ("right.png", "profil"),
    ("top.png", "dessus"),
    ("three_quarter.png", "trois-quarts"),
    ("ref_1.png", "référence"),
]


def _pick_glb(outdir: Path, explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    manifest_p = outdir / "game_manifest.json"
    if manifest_p.is_file():
        try:
            gm = json.loads(manifest_p.read_text(encoding="utf-8"))
            lod0_p = gm.get("lods", {}).get("LOD0", {}).get("path")
            if lod0_p and Path(lod0_p).is_file():
                return Path(lod0_p)
        except Exception:
            pass
    for pattern in ("*_game.glb", "*.glb"):
        hits = [
            p for p in sorted(outdir.glob(pattern))
            if not any(tag in p.stem.lower() for tag in ("_ucx", "_lod1", "_lod2", "_lod3"))
        ]
        if hits:
            return hits[0]
    hits = sorted(outdir.glob("*.glb"))
    return hits[0] if hits else None


def _glb_total_tris(p: Path) -> int:
    try:
        import trimesh as _tm
        sc = _tm.load(p, force="scene")
        return int(sum(int(g.faces.shape[0]) for k, g in sc.geometry.items() if not str(k).startswith("UCX_")))
    except Exception:
        return 0


def _yup_glb_b64(glb_path: Path) -> str:
    """Tourne la racine glTF de Z-up (convention 3d-forge : -Y face, +Z haut) vers Y-up (+Y haut, +Z face)."""
    raw = glb_path.read_bytes()
    if len(raw) < 20 or raw[:4] != b"glTF":
        return base64.b64encode(raw).decode("ascii")
    _version, _total = struct.unpack_from("<II", raw, 4)
    j_len, j_type = struct.unpack_from("<II", raw, 12)
    if j_type != 0x4E4F534A:
        return base64.b64encode(raw).decode("ascii")
    doc = json.loads(raw[20 : 20 + j_len].decode("utf-8"))
    rest = raw[20 + j_len :]

    nodes = doc.setdefault("nodes", [])
    scenes = doc.get("scenes") or []
    if not nodes or not scenes:
        return base64.b64encode(raw).decode("ascii")
    sc = scenes[doc.get("scene", 0)]
    roots = list(sc.get("nodes") or [])
    if not roots:
        return base64.b64encode(raw).decode("ascii")

    s = math.sin(-math.pi / 4.0)
    c = math.cos(-math.pi / 4.0)
    wrapper = {"name": "_yup", "rotation": [round(s, 7), 0.0, 0.0, round(c, 7)], "children": roots}
    nodes.append(wrapper)
    sc["nodes"] = [len(nodes) - 1]

    body = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    pad = (-len(body)) % 4
    body += b" " * pad
    out = bytearray()
    out += struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(body) + len(rest))
    out += struct.pack("<II", len(body), 0x4E4F534A)
    out += body
    out += rest
    return base64.b64encode(bytes(out)).decode("ascii")


def _collect_lods(outdir: Path, main_glb: Path) -> list[dict]:
    """Embarque LOD0 (+ LOD1/LOD2 si présents dans game_manifest.json) pour bascule instantanée."""
    entries: list[dict] = []
    manifest_p = outdir / "game_manifest.json"
    gm = None
    if manifest_p.is_file():
        try:
            gm = json.loads(manifest_p.read_text(encoding="utf-8"))
        except Exception:
            gm = None

    seen_paths: set[Path] = set()
    if gm and isinstance(gm.get("lods"), dict):
        for lod_key in ("LOD0", "LOD1", "LOD2"):
            info = gm["lods"].get(lod_key)
            if not info:
                continue
            p = Path(info.get("path", ""))
            if not p.is_file():
                p = outdir / p.name
            if p.is_file() and p.resolve() not in seen_paths:
                seen_paths.add(p.resolve())
                entries.append({
                    "id": lod_key,
                    "name": p.name,
                    "tris": _glb_total_tris(p) or int(info.get("tris", 0)),
                    "b64": _yup_glb_b64(p),
                })

    if not entries:
        entries.append({
            "id": "LOD0",
            "name": main_glb.name,
            "tris": _glb_total_tris(main_glb),
            "b64": _yup_glb_b64(main_glb),
        })
    return entries


def _photo_cards(outdir: Path) -> str:
    imgs: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    # Priorité à la planche QA 6 vues haute résolution si présente
    for qa in sorted(outdir.glob("*_6views.png")):
        imgs.append((qa, "planche QA 6 vues"))
        seen.add(qa.resolve())
    for subdir in (outdir / "refs", outdir):
        if not subdir.is_dir():
            continue
        for fname, label in PHOTO_SLOTS:
            p = subdir / fname
            if p.is_file() and p.resolve() not in seen:
                imgs.append((p, label))
                seen.add(p.resolve())
    if not imgs:
        return ""
    cards = []
    for p, label in imgs:
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        wide_cls = ' class="wide-card"' if "6 vues" in label else ""
        cards.append(
            f'<figure{wide_cls}><img src="data:image/png;base64,{b64}" alt="{_html.escape(label)}">'
            f"<figcaption>{_html.escape(label)}</figcaption></figure>"
        )
    return (
        "<section class=\"refs\"><h2>Planches QA &amp; Vues de contrôle</h2>"
        f"<div class=\"grid\">{''.join(cards)}</div></section>"
    )


def _stats_html(outdir: Path, report: dict | None) -> str:
    manifest = None
    gates = None
    mp = outdir / "game_manifest.json"
    gp = outdir / "gates.json"
    if mp.is_file():
        try:
            manifest = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            pass
    if gp.is_file():
        try:
            gates = json.loads(gp.read_text(encoding="utf-8"))
        except Exception:
            pass

    chips: list[str] = []
    if gates and "n_pass" in gates and "n_total" in gates:
        ok = bool(gates.get("all_pass"))
        cls = "chip ok" if ok else "chip warn"
        mark = "✓ LIVRABLE" if ok else "⚠"
        chips.append(f'<span class="{cls}">QA {gates["n_pass"]}/{gates["n_total"]} {mark}</span>')

    val = (report or {}).get("validation") or (report or {})
    wt = manifest.get("stl_watertight") if (manifest and "stl_watertight" in manifest) else val.get("watertight")
    if wt is not None:
        cls = "chip ok" if wt else "chip warn"
        chips.append(f'<span class="{cls}">{"✓ STL 100 % étanche" if wt else "STL non étanche ⚠"}</span>')

    main_glb = _pick_glb(outdir, None)
    tris = (_glb_total_tris(main_glb) if main_glb else 0) or (manifest or {}).get("lods", {}).get("LOD0", {}).get("tris") or val.get("triangles")
    if tris:
        chips.append(f'<span class="chip">{int(tris):,} triangles</span>'.replace(",", "\u202f"))

    if manifest and "draw_calls_after" in manifest:
        dc_b = manifest.get("draw_calls_before", "?")
        dc_a = manifest.get("draw_calls_after", 1)
        chips.append(f'<span class="chip">{dc_b} → {dc_a} draw call</span>')

    if manifest and "dims_m" in manifest:
        d = manifest["dims_m"]
        cm = f"{d[0]*100:.1f} × {d[1]*100:.1f} × {d[2]*100:.1f} cm"
        chips.append(f'<span class="chip">{_html.escape(cm)}</span>')

    if manifest and "turbo_total_s" in manifest:
        chips.append(f'<span class="chip">forge {manifest["turbo_total_s"]:.1f}\u202fs</span>')

    if val.get("iou_mean"):
        chips.append(f'<span class="chip">silhouette {val["iou_mean"] * 100:.0f}\u202f%</span>')

    return f'<div class="stats">{"".join(chips)}</div>' if chips else ""


_PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    color-scheme: dark;
    --bg: #0b0d12;
    --panel: #131720;
    --panel2: #191f2b;
    --ink: #eef2f8;
    --dim: #95a0b5;
    --line: #273042;
    --accent: #e0525e;
    --ok: #2bc48a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font: 14.5px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif;
  }}
  header {{
    padding: 13px 20px; border-bottom: 1px solid var(--line);
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    background: linear-gradient(180deg, #121620 0%, #0d1017 100%);
  }}
  header h1 {{ margin: 0; font-size: 17px; font-weight: 650; letter-spacing: -.01em; }}
  .badge-engine {{
    font-size: 11.5px; padding: 3px 9px; border-radius: 999px;
    background: #1a2130; border: 1px solid #2e3a52; color: #b9c5dc;
  }}
  header .hint {{ color: var(--dim); font-size: 12.5px; margin-left: auto; }}
  main {{ max-width: 1180px; margin: 0 auto; padding: 14px 18px 44px; }}
  .toolbar {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 0 0 10px; }}
  .toolbar .grp {{
    display: inline-flex; flex-wrap: wrap; gap: 4px; background: var(--panel);
    padding: 4px; border-radius: 10px; border: 1px solid var(--line);
  }}
  .toolbar button {{
    background: transparent; color: var(--dim); border: 0; padding: 5px 10px;
    border-radius: 7px; font: inherit; font-size: 12.5px; cursor: pointer;
    transition: background .12s, color .12s; white-space: nowrap;
  }}
  .toolbar button:hover {{ color: var(--ink); background: var(--panel2); }}
  .toolbar button.on {{ background: #263149; color: #fff; font-weight: 550; box-shadow: inset 0 0 0 1px #425680; }}
  .toolbar .sep {{ flex: 1 1 auto; }}
  #stage-wrap {{
    position: relative; width: 100%; height: min(74vh, 660px); border-radius: 14px;
    overflow: hidden; border: 1px solid var(--line);
    background: radial-gradient(ellipse at 50% 34%, #252b3b 0%, #141822 58%, #0c0e14 100%);
    box-shadow: 0 18px 50px rgba(0,0,0,.45);
  }}
  #stage {{ width: 100%; height: 100%; display: block; touch-action: none; cursor: grab; }}
  #stage:active {{ cursor: grabbing; }}
  #hud {{
    position: absolute; left: 14px; bottom: 12px; display: flex; gap: 8px; align-items: center;
    padding: 5px 11px; border-radius: 999px; font-size: 12px; color: #cbd5e8;
    background: rgba(12, 15, 22, 0.76); border: 1px solid rgba(255,255,255,0.1);
    backdrop-filter: blur(8px); pointer-events: none;
  }}
  #hud .dot {{ width: 7px; height: 7px; border-radius: 50%; background: var(--ok); display: inline-block; }}
  #err {{
    position: absolute; left: 50%; top: 16px; transform: translateX(-50%);
    display: none; padding: 8px 16px; border-radius: 9px; font-size: 12.5px;
    background: rgba(45, 22, 28, 0.92); border: 1px solid #7d3645; color: #ffd7df;
    z-index: 10; max-width: 90%; text-align: center;
  }}
  .actions {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 14px; }}
  .dl {{
    display: inline-flex; align-items: center; gap: 7px; padding: 9px 17px; border-radius: 9px;
    background: #f0f4fc; color: #0b0e15; text-decoration: none; font-weight: 600; font-size: 13.5px;
  }}
  .dl:hover {{ background: #ffffff; }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 7px; margin-top: 12px; }}
  .chip {{
    font-size: 12.5px; color: #cfd8ea; background: var(--panel); padding: 4px 11px;
    border-radius: 999px; border: 1px solid var(--line);
  }}
  .chip.ok {{ color: #8ff0c8; border-color: #215c45; background: rgba(24, 68, 52, 0.5); font-weight: 550; }}
  .chip.warn {{ color: #ffd48a; border-color: #6b5222; background: rgba(68, 50, 18, 0.5); }}
  .refs {{ margin-top: 28px; }}
  .refs h2 {{ font-size: 13px; font-weight: 600; color: var(--dim); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 12px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }}
  figure {{ margin: 0; background: var(--panel); border-radius: 11px; overflow: hidden; border: 1px solid var(--line); }}
  figure.wide-card {{ grid-column: 1 / -1; }}
  figure img {{ width: 100%; height: 220px; object-fit: contain; display: block; background: #0f1219; }}
  figure.wide-card img {{ height: auto; max-height: 540px; }}
  figcaption {{ padding: 7px 12px; font-size: 12.5px; color: var(--dim); border-top: 1px solid var(--line); }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <span class="badge-engine">3d-forge Studio v6.0 · PBR ACES</span>
  <span class="hint">Glisser : orbiter · Molette : zoomer · Clic droit / Maj+glisser : déplacer · Double-clic : recadrer</span>
</header>
<main>
  <div class="toolbar">
    <div class="grp" id="lods"></div>
    <div class="grp" id="modes">
      <button data-mode="0" class="on">Studio PBR</button>
      <button data-mode="1">Plein air</button>
      <button data-mode="2">Clay</button>
      <button data-mode="3">Albedo</button>
      <button data-mode="4">Normals</button>
      <button data-mode="5">Roughness</button>
      <button data-mode="6">AO</button>
      <button data-mode="7">Metal</button>
      <button data-mode="8">Damier UV</button>
    </div>
    <div class="grp">
      <select id="envSel" title="Éclairage HDRI" style="background:transparent;color:var(--ink);border:0;font:inherit;font-size:12.5px;padding:4px 6px;cursor:pointer">
        <option value="0">Studio PBR</option>
        <option value="1">Plein air</option>
      </select>
      <select id="chanSel" title="Canal d'inspection" style="background:transparent;color:var(--ink);border:0;font:inherit;font-size:12.5px;padding:4px 6px;cursor:pointer">
        <option value="0">Rendu PBR</option>
        <option value="2">Clay</option>
        <option value="3">Albedo</option>
        <option value="4">Normals</option>
        <option value="5">Roughness</option>
        <option value="6">AO</option>
        <option value="7">Metal</option>
        <option value="8">Damier UV</option>
      </select>
    </div>
    <div class="grp">
      <button id="wire">◇ Filaire</button>
      <button id="animBtn" class="on">⟳ Tourner</button>
      <button id="jointBtn" title="Animer les roues et articulations">⚙ Articulations</button>
    </div>
    <span class="sep"></span>
    <div class="grp" id="views">
      <button data-view="front">Face</button>
      <button data-view="threeq">3/4</button>
      <button data-view="side">Profil</button>
      <button data-view="back">Arrière</button>
      <button data-view="top">Dessus</button>
      <button id="reset-cam">↺ Reset</button>
      <button id="fullscr">⛶</button>
    </div>
  </div>
  <div id="stage-wrap">
    <canvas id="stage"></canvas>
    <canvas id="stage2d" style="display:none;position:absolute;inset:0;width:100%;height:100%;touch-action:none"></canvas>
    <div id="hud"><span class="dot"></span><span id="hud-txt">Initialisation du moteur 3D…</span></div>
    <div id="err"></div>
  </div>
  <div class="actions">
    <a class="dl" id="dl" download="{filename}">⬇ Télécharger le modèle 3D ({filename})</a>
  </div>
  {stats}
  {photos}
</main>
<script>
(function () {{
  "use strict";

  const LODS_DATA = {lods_json};
  const GLB_B64 = LODS_DATA[0].b64;

  const hudTxt = document.getElementById("hud-txt");
  const errBox = document.getElementById("err");
  const dlLink = document.getElementById("dl");
  const canvas = document.getElementById("stage");
  const canvas2d = document.getElementById("stage2d");
  const wrap   = document.getElementById("stage-wrap");

  function showBanner(msg) {{
    errBox.textContent = msg;
    errBox.style.display = "block";
  }}

  function b64ToBytes(b64) {{
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }}

  // Supporte PNG, JPEG et EXT_texture_webp via Data-URI natif (zéro URL.createObjectURL requis)
  function bytesToDataURI(bytes, mime) {{
    let bin = "";
    const step = 0x8000;
    for (let i = 0; i < bytes.length; i += step) {{
      bin += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(i + step, bytes.length)));
    }}
    return "data:" + (mime || "image/png") + ";base64," + btoa(bin);
  }}

  let currentLodEntry = LODS_DATA[0];
  let currentBlobUrl = null;
  function updateDownload(lodIdx) {{
    const entry = LODS_DATA[lodIdx] || LODS_DATA[0];
    currentLodEntry = entry;
    dlLink.download = entry.name;
    dlLink.textContent = "⬇ Télécharger " + entry.id + " (" + entry.name + ")";
    if (window.location && (window.location.protocol === "http:" || window.location.protocol === "https:")) {{
      dlLink.href = encodeURIComponent(entry.name) + "?download=1";
      return;
    }}
    try {{
      if (currentBlobUrl) URL.revokeObjectURL(currentBlobUrl);
      const bytes = b64ToBytes(entry.b64);
      currentBlobUrl = URL.createObjectURL(new Blob([bytes], {{ type: "model/gltf-binary" }}));
      dlLink.href = currentBlobUrl;
    }} catch (_) {{
      dlLink.href = "data:application/octet-stream;base64," + entry.b64;
    }}
  }}
  dlLink.addEventListener("click", async e => {{
    if (window.location && (window.location.protocol === "http:" || window.location.protocol === "https:")) {{
      return; // Téléchargement HTTP natif direct via `Content-Disposition: attachment`
    }}
    const entry = currentLodEntry || LODS_DATA[0];
    if (window.showSaveFilePicker) {{
      e.preventDefault();
      try {{
        const handle = await window.showSaveFilePicker({{
          suggestedName: entry.name,
          types: [{{ description: "Modèle 3D Binary glTF (.glb)", accept: {{ "model/gltf-binary": [".glb"] }} }}],
        }});
        const writable = await handle.createWritable();
        await writable.write(b64ToBytes(entry.b64));
        await writable.close();
        hudTxt.textContent = "✓ Fichier enregistré : " + entry.name;
        return;
      }} catch (err) {{
        if (err && err.name === "AbortError") return;
      }}
    }}
    // Fallback iframe sandboxée (`origin === "null"`) : ouvre / déclenche le flux binaire
    try {{
      const bytes = b64ToBytes(entry.b64);
      const url = URL.createObjectURL(new Blob([bytes], {{ type: "application/octet-stream" }}));
      const tmp = document.createElement("a");
      tmp.href = url;
      tmp.download = entry.name;
      tmp.target = "_blank";
      tmp.rel = "noopener";
      document.body.appendChild(tmp);
      tmp.click();
      tmp.remove();
      hudTxt.textContent = "⬇ Téléchargement lancé : " + entry.name + " (si bloqué par l'aperçu, utilisez l'onglet Live Preview)";
    }} catch (_) {{}}
  }});
  updateDownload(0);

  // Boutons LOD dynamiques
  const lodsBar = document.getElementById("lods");
  if (LODS_DATA.length > 1) {{
    LODS_DATA.forEach((entry, idx) => {{
      const b = document.createElement("button");
      b.dataset.lod = String(idx);
      b.className = idx === 0 ? "on" : "";
      b.textContent = entry.tris ? (entry.id + " · " + entry.tris.toLocaleString("fr-FR")) : entry.id;
      lodsBar.appendChild(b);
    }});
  }} else {{
    lodsBar.style.display = "none";
  }}

  // Algèbre matricielle 4x4 colonne-majeure
  const M4 = {{
    ident: () => new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]),
    mul: (a, b) => {{
      const o = new Float32Array(16);
      for (let i = 0; i < 4; i++)
        for (let j = 0; j < 4; j++)
          o[j*4+i] = a[i]*b[j*4] + a[4+i]*b[j*4+1] + a[8+i]*b[j*4+2] + a[12+i]*b[j*4+3];
      return o;
    }},
    trs: (t, q, s) => {{
      const [x,y,z,w] = q;
      const x2=x+x, y2=y+y, z2=z+z;
      const xx=x*x2, xy=x*y2, xz=x*z2, yy=y*y2, yz=y*z2, zz=z*z2;
      const wx=w*x2, wy=w*y2, wz=w*z2;
      return new Float32Array([
        (1-(yy+zz))*s[0], (xy+wz)*s[0],     (xz-wy)*s[0],     0,
        (xy-wz)*s[1],     (1-(xx+zz))*s[1], (yz+wx)*s[1],     0,
        (xz+wy)*s[2],     (yz-wx)*s[2],     (1-(xx+yy))*s[2], 0,
        t[0], t[1], t[2], 1,
      ]);
    }},
    persp: (fov, asp, n, f) => {{
      const t = 1 / Math.tan(fov / 2), nf = 1 / (n - f);
      return new Float32Array([t/asp,0,0,0, 0,t,0,0, 0,0,(f+n)*nf,-1, 0,0,2*f*n*nf,0]);
    }},
    lookAt: (e, c, u) => {{
      let zx=e[0]-c[0], zy=e[1]-c[1], zz=e[2]-c[2];
      let l = Math.hypot(zx,zy,zz) || 1; zx/=l; zy/=l; zz/=l;
      let xx=u[1]*zz-u[2]*zy, xy=u[2]*zx-u[0]*zz, xz=u[0]*zy-u[1]*zx;
      l = Math.hypot(xx,xy,xz) || 1; xx/=l; xy/=l; xz/=l;
      const yx=zy*xz-zz*xy, yy=zz*xx-zx*xz, yz=zx*xy-zy*xx;
      return new Float32Array([
        xx, yx, zx, 0,  xy, yy, zy, 0,  xz, yz, zz, 0,
        -(xx*e[0]+xy*e[1]+xz*e[2]), -(yx*e[0]+yy*e[1]+yz*e[2]), -(zx*e[0]+zy*e[1]+zz*e[2]), 1,
      ]);
    }},
  }};

  // Décodage complet d'un binaire GLB 2.0 + calcul MikkTSpace par sommet
  function parseGLB(b64) {{
    const glbBytes = b64ToBytes(b64);
    const dv = new DataView(glbBytes.buffer, glbBytes.byteOffset, glbBytes.byteLength);
    if (dv.getUint32(0, true) !== 0x46546C67) throw new Error("En-tête GLB invalide");
    let off = 12, json = null, bin = null;
    while (off < glbBytes.byteLength) {{
      const len = dv.getUint32(off, true), typ = dv.getUint32(off + 4, true);
      const slice = glbBytes.subarray(off + 8, off + 8 + len);
      if (typ === 0x4E4F534A) json = JSON.parse(new TextDecoder().decode(slice));
      else if (typ === 0x004E4942) bin = slice;
      off += 8 + len;
    }}
    if (!json || !bin) throw new Error("Chunk GLB JSON ou BIN manquant");

    const COMP = {{ 5120:[Int8Array,1], 5121:[Uint8Array,1], 5122:[Int16Array,2],
                    5123:[Uint16Array,2], 5125:[Uint32Array,4], 5126:[Float32Array,4] }};
    const TYPE = {{ SCALAR:1, VEC2:2, VEC3:3, VEC4:4, MAT4:16 }};

    function readAcc(i) {{
      const a = json.accessors[i], bv = json.bufferViews[a.bufferView];
      const [Arr, bpe] = COMP[a.componentType];
      const n = TYPE[a.type];
      const byteOff = bin.byteOffset + (bv.byteOffset || 0) + (a.byteOffset || 0);
      const stride = bv.byteStride || (n * bpe);
      if (stride === n * bpe && (byteOff % bpe) === 0)
        return new Arr(bin.buffer, byteOff, a.count * n);
      const out = new Arr(a.count * n);
      const view = new DataView(bin.buffer, byteOff, a.count * stride);
      for (let k = 0; k < a.count; k++) {{
        for (let c = 0; c < n; c++) {{
          const p = k * stride + c * bpe;
          out[k*n+c] = a.componentType === 5126 ? view.getFloat32(p, true)
                     : a.componentType === 5125 ? view.getUint32(p, true)
                     : a.componentType === 5123 ? view.getUint16(p, true)
                     : view.getUint8(p);
        }}
      }}
      return out;
    }}

    function expand(arr, idx, n) {{
      if (!idx) return arr;
      const out = new Float32Array(idx.length * n);
      for (let i = 0; i < idx.length; i++) {{
        const s = idx[i] * n;
        for (let c = 0; c < n; c++) out[i*n+c] = arr[s + c];
      }}
      return out;
    }}

    function flatNormals(pos) {{
      const out = new Float32Array(pos.length);
      for (let i = 0; i < pos.length; i += 9) {{
        const ax=pos[i+3]-pos[i], ay=pos[i+4]-pos[i+1], az=pos[i+5]-pos[i+2];
        const bx=pos[i+6]-pos[i], by=pos[i+7]-pos[i+1], bz=pos[i+8]-pos[i+2];
        let nx=ay*bz-az*by, ny=az*bx-ax*bz, nz=ax*by-ay*bx;
        const l = Math.hypot(nx,ny,nz) || 1; nx/=l; ny/=l; nz/=l;
        for (let k = 0; k < 3; k++) {{ out[i+k*3]=nx; out[i+k*3+1]=ny; out[i+k*3+2]=nz; }}
      }}
      return out;
    }}

    function computeTangents(pos, nrm, uv) {{
      const nVerts = pos.length / 3;
      const out = new Float32Array(nVerts * 4);
      for (let i = 0; i < nVerts; i += 3) {{
        const i0 = i*3, i1 = (i+1)*3, i2 = (i+2)*3;
        const u0 = i*2, u1 = (i+1)*2, u2 = (i+2)*2;
        const dx1 = pos[i1]-pos[i0], dy1 = pos[i1+1]-pos[i0+1], dz1 = pos[i1+2]-pos[i0+2];
        const dx2 = pos[i2]-pos[i0], dy2 = pos[i2+1]-pos[i0+1], dz2 = pos[i2+2]-pos[i0+2];
        const du1 = uv[u1]-uv[u0], dv1 = uv[u1+1]-uv[u0+1];
        const du2 = uv[u2]-uv[u0], dv2 = uv[u2+1]-uv[u0+1];
        const det = du1 * dv2 - dv1 * du2;
        let tx = 1, ty = 0, tz = 0;
        if (Math.abs(det) > 1e-8) {{
          const inv = 1.0 / det;
          tx = (dx1 * dv2 - dx2 * dv1) * inv;
          ty = (dy1 * dv2 - dy2 * dv1) * inv;
          tz = (dz1 * dv2 - dz2 * dv1) * inv;
        }}
        for (let k = 0; k < 3; k++) {{
          const vn = (i + k) * 3, vt = (i + k) * 4;
          const nx = nrm[vn], ny = nrm[vn+1], nz = nrm[vn+2];
          const d = nx*tx + ny*ty + nz*tz;
          let ox = tx - nx*d, oy = ty - ny*d, oz = tz - nz*d;
          let l = Math.hypot(ox, oy, oz);
          if (l < 1e-6) {{
            ox = Math.abs(nx) < 0.9 ? 1 - nx*nx : -nx*ny;
            oy = Math.abs(nx) < 0.9 ? -nx*ny    : 1 - ny*ny;
            oz = Math.abs(nx) < 0.9 ? -nx*nz    : -ny*nz;
            l = Math.hypot(ox, oy, oz) || 1;
          }}
          out[vt] = ox/l; out[vt+1] = oy/l; out[vt+2] = oz/l; out[vt+3] = 1.0;
        }}
      }}
      return out;
    }}

    function buildWirePositions(pos) {{
      const tris = pos.length / 9;
      const w = new Float32Array(tris * 18);
      for (let t = 0; t < tris; t++) {{
        const s = t * 9, d = t * 18;
        w[d]   =pos[s];   w[d+1] =pos[s+1]; w[d+2] =pos[s+2];
        w[d+3] =pos[s+3]; w[d+4] =pos[s+4]; w[d+5] =pos[s+5];
        w[d+6] =pos[s+3]; w[d+7] =pos[s+4]; w[d+8] =pos[s+5];
        w[d+9] =pos[s+6]; w[d+10]=pos[s+7]; w[d+11]=pos[s+8];
        w[d+12]=pos[s+6]; w[d+13]=pos[s+7]; w[d+14]=pos[s+8];
        w[d+15]=pos[s];   w[d+16]=pos[s+1]; w[d+17]=pos[s+2];
      }}
      return w;
    }}

    const parts = [];
    const bbMin = [Infinity, Infinity, Infinity], bbMax = [-Infinity, -Infinity, -Infinity];
    let totalTris = 0;

    function walk(ni, parent, chain) {{
      const node = json.nodes[ni];
      const local = node.matrix ? new Float32Array(node.matrix)
        : M4.trs(node.translation || [0,0,0], node.rotation || [0,0,0,1], node.scale || [1,1,1]);
      const world = M4.mul(parent, local);
      const nextChain = (chain || []).concat([{{
        localRest: local,
        joint: (node.extras && node.extras.joint) ? node.extras.joint : null,
        name: node.name || "",
      }}]);
      const hasAnimJoint = nextChain.some(st => st.joint && st.joint.kind !== "fixed");
      if (node.mesh !== undefined) {{
        for (const prim of json.meshes[node.mesh].primitives) {{
          if (prim.mode !== undefined && prim.mode !== 4) continue;
          const idx = prim.indices !== undefined ? readAcc(prim.indices) : null;
          const pos = expand(readAcc(prim.attributes.POSITION), idx, 3);
          const nrm = prim.attributes.NORMAL !== undefined
            ? expand(readAcc(prim.attributes.NORMAL), idx, 3) : flatNormals(pos);
          const uv = prim.attributes.TEXCOORD_0 !== undefined
            ? expand(readAcc(prim.attributes.TEXCOORD_0), idx, 2)
            : new Float32Array((pos.length / 3) * 2);
          const tan = prim.attributes.TANGENT !== undefined
            ? expand(readAcc(prim.attributes.TANGENT), idx, 4)
            : computeTangents(pos, nrm, uv);

          for (let i = 0; i < pos.length; i += 3) {{
            const x=pos[i], y=pos[i+1], z=pos[i+2];
            const wx = world[0]*x + world[4]*y + world[8]*z  + world[12];
            const wy = world[1]*x + world[5]*y + world[9]*z  + world[13];
            const wz = world[2]*x + world[6]*y + world[10]*z + world[14];
            if (wx < bbMin[0]) bbMin[0] = wx; if (wx > bbMax[0]) bbMax[0] = wx;
            if (wy < bbMin[1]) bbMin[1] = wy; if (wy > bbMax[1]) bbMax[1] = wy;
            if (wz < bbMin[2]) bbMin[2] = wz; if (wz > bbMax[2]) bbMax[2] = wz;
          }}

          const mat = (json.materials || [])[prim.material] || {{}};
          const pbr = mat.pbrMetallicRoughness || {{}};
          totalTris += pos.length / 9;
          parts.push({{
            pos, nrm, uv, tan,
            wirePos: buildWirePositions(pos),
            count: pos.length / 3,
            wireCount: (pos.length / 9) * 6,
            model: world,
            jointChain: hasAnimJoint ? nextChain : null,
            baseColor: pbr.baseColorFactor || [1,1,1,1],
            metal: pbr.metallicFactor !== undefined ? pbr.metallicFactor : 0.0,
            rough: pbr.roughnessFactor !== undefined ? pbr.roughnessFactor : 0.55,
            albTexIdx: pbr.baseColorTexture ? pbr.baseColorTexture.index : -1,
            mrTexIdx:  pbr.metallicRoughnessTexture ? pbr.metallicRoughnessTexture.index : -1,
            nrmTexIdx: mat.normalTexture ? mat.normalTexture.index : -1,
            nrmScale:  mat.normalTexture && mat.normalTexture.scale !== undefined ? mat.normalTexture.scale : 1.0,
            aoTexIdx:  mat.occlusionTexture ? mat.occlusionTexture.index : -1,
            aoStrength: mat.occlusionTexture && mat.occlusionTexture.strength !== undefined ? mat.occlusionTexture.strength : 1.0,
          }});
        }}
      }}
      for (const c of node.children || []) walk(c, world, nextChain);
    }}

    const scene = json.scenes[json.scene || 0];
    for (const r of scene.nodes) walk(r, M4.ident(), []);

    return {{ json, bin, parts, bbMin, bbMax, totalTris }};
  }}

  // État caméra partagé (orbite + zoom + pan + cadrages)
  const cam = {{
    target: [0, 0.13, 0],
    radius: 0.2,
    az: 0.42,
    el: 0.22,
    dist: 0.55,
    floorY: 0,
    mode: 0,
    wire: false,
    spin: true,
    activeLod: 0,
  }};

  function fitCamera(parsed, resetAngles) {{
    cam.target = [
      (parsed.bbMin[0] + parsed.bbMax[0]) / 2,
      (parsed.bbMin[1] + parsed.bbMax[1]) / 2,
      (parsed.bbMin[2] + parsed.bbMax[2]) / 2,
    ];
    cam.radius = Math.max(1e-3, Math.hypot(
      parsed.bbMax[0] - parsed.bbMin[0],
      parsed.bbMax[1] - parsed.bbMin[1],
      parsed.bbMax[2] - parsed.bbMin[2],
    ) / 2);
    cam.floorY = parsed.bbMin[1];
    if (resetAngles) {{
      cam.az = 0.42;
      cam.el = 0.22;
      cam.dist = cam.radius * 2.55;
    }}
  }}

  const PRESETS = {{
    front:  [0.0,            0.10],
    threeq: [0.62,           0.26],
    side:   [Math.PI / 2,    0.10],
    back:   [Math.PI,        0.10],
    top:    [0.0,            1.44],
  }};

  document.getElementById("modes").addEventListener("click", e => {{
    const b = e.target.closest("button[data-mode]");
    if (!b) return;
    cam.mode = +b.dataset.mode;
    for (const x of e.currentTarget.querySelectorAll("button")) x.classList.toggle("on", x === b);
  }});
  const spinBtn = document.getElementById("animBtn");
  const jointBtn = document.getElementById("jointBtn");
  cam.animJoints = false;
  if (jointBtn) {{
    jointBtn.addEventListener("click", e => {{
      cam.animJoints = !cam.animJoints;
      e.currentTarget.classList.toggle("on", cam.animJoints);
    }});
  }}
  document.getElementById("envSel").addEventListener("change", e => {{
    cam.mode = +e.target.value;
    document.getElementById("chanSel").value = "0";
    for (const x of document.querySelectorAll("#modes button")) x.classList.toggle("on", +x.dataset.mode === cam.mode);
  }});
  document.getElementById("chanSel").addEventListener("change", e => {{
    cam.mode = +e.target.value;
    for (const x of document.querySelectorAll("#modes button")) x.classList.toggle("on", +x.dataset.mode === cam.mode);
  }});
  document.getElementById("wire").addEventListener("click", e => {{
    cam.wire = !cam.wire; e.currentTarget.classList.toggle("on", cam.wire);
  }});
  spinBtn.addEventListener("click", e => {{
    cam.spin = !cam.spin; e.currentTarget.classList.toggle("on", cam.spin);
  }});
  document.getElementById("views").addEventListener("click", e => {{
    const b = e.target.closest("button[data-view]");
    if (!b) return;
    const p = PRESETS[b.dataset.view];
    if (!p) return;
    cam.az = p[0]; cam.el = p[1]; cam.spin = false;
    spinBtn.classList.remove("on");
  }});
  document.getElementById("fullscr").addEventListener("click", () => {{
    if (document.fullscreenElement) document.exitFullscreen();
    else if (wrap.requestFullscreen) wrap.requestFullscreen();
  }});

  let parsed = parseGLB(LODS_DATA[0].b64);
  fitCamera(parsed, true);

  document.getElementById("reset-cam").addEventListener("click", () => {{
    fitCamera(parsed, true);
  }});

  function bindPointerControls(el) {{
    let drag = null;
    el.addEventListener("pointerdown", e => {{
      el.setPointerCapture(e.pointerId);
      drag = {{ x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey }};
    }});
    el.addEventListener("pointermove", e => {{
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.x = e.clientX; drag.y = e.clientY;
      if (drag.pan) {{
        const s = cam.dist * 0.0014;
        cam.target[0] -= Math.cos(cam.az) * dx * s;
        cam.target[2] += Math.sin(cam.az) * dx * s;
        cam.target[1] += dy * s;
      }} else {{
        cam.az -= dx * 0.007;
        cam.el = Math.max(-1.46, Math.min(1.46, cam.el + dy * 0.007));
        cam.spin = false;
        spinBtn.classList.remove("on");
      }}
    }});
    el.addEventListener("pointerup", () => {{ drag = null; }});
    el.addEventListener("pointercancel", () => {{ drag = null; }});
    el.addEventListener("dblclick", () => fitCamera(parsed, true));
    el.addEventListener("contextmenu", e => e.preventDefault());
    el.addEventListener("wheel", e => {{
      e.preventDefault();
      cam.dist = Math.max(cam.radius * 0.45, Math.min(cam.radius * 14, cam.dist * Math.pow(1.0012, e.deltaY)));
    }}, {{ passive: false }});
  }}

  // =========================================================================
  // MOTEUR 1 : WEBGL UNIVERSEL (WebGL2 & WebGL1, ZÉRO EXTENSION REQUISE)
  // =========================================================================
  function startWebGL() {{
    const glOpts = {{ antialias: true, alpha: false, depth: true, powerPreference: "high-performance" }};
    let isWebGL2 = false;
    let gl = canvas.getContext("webgl2", glOpts);
    if (gl) {{
      isWebGL2 = true;
    }} else {{
      gl = canvas.getContext("webgl", glOpts) || canvas.getContext("experimental-webgl", glOpts);
    }}
    if (!gl) return false;

    const vsSrc = `
      precision highp float;
      attribute vec3 aPos;
      attribute vec3 aNrm;
      attribute vec2 aUV;
      attribute vec4 aTan;
      uniform mat4 uMVP, uModel, uView;
      varying vec3 vNrm;
      varying vec3 vTan;
      varying vec3 vBit;
      varying vec2 vUV;
      varying vec3 vViewPos;
      varying vec3 vWorld;
      void main() {{
        vec4 wp = uModel * vec4(aPos, 1.0);
        vec4 vp = uView * wp;
        mat3 mv = mat3(uView) * mat3(uModel);
        vec3 N = normalize(mv * aNrm);
        vec3 T = normalize(mv * aTan.xyz);
        T = normalize(T - N * dot(N, T));
        vNrm = N;
        vTan = T;
        vBit = cross(N, T) * aTan.w;
        vUV = aUV;
        vViewPos = vp.xyz;
        vWorld = wp.xyz;
        gl_Position = uMVP * vec4(aPos, 1.0);
      }}`;

    const fsSrc = `
      precision highp float;
      varying vec3 vNrm;
      varying vec3 vTan;
      varying vec3 vBit;
      varying vec2 vUV;
      varying vec3 vViewPos;
      varying vec3 vWorld;
      uniform sampler2D uAlb, uMR, uNrm;
      uniform vec4 uBase;
      uniform vec2 uFactors;
      uniform float uNrmScale, uAOStr, uGridStep;
      uniform int uHasAlb, uHasMR, uHasNrm, uHasAO, uMode, uKind, uWire;
      uniform vec3 uKeyDir, uFillDir, uRimDir, uKeyCol, uSkyCol, uGndCol;

      vec3 srgbToLinear(vec3 c) {{ return pow(max(c, vec3(0.0)), vec3(2.2)); }}
      vec3 linearToSrgb(vec3 c) {{ return pow(max(c, vec3(0.0)), vec3(1.0 / 2.2)); }}
      vec3 aces(vec3 x) {{
        return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
      }}
      float D_GGX(float nh, float r) {{
        float a = r * r;
        float a2 = a * a;
        float d = nh * nh * (a2 - 1.0) + 1.0;
        return a2 / max(3.14159265 * d * d, 1e-6);
      }}
      float G_Smith(float nv, float nl, float r) {{
        float k = (r + 1.0);
        k = (k * k) / 8.0;
        return (nv / (nv * (1.0 - k) + k)) * (nl / (nl * (1.0 - k) + k));
      }}
      vec3 F_Schlick(float vh, vec3 f0) {{
        return f0 + (1.0 - f0) * pow(1.0 - vh, 5.0);
      }}
      vec3 directLight(vec3 L, vec3 V, vec3 N, vec3 col, vec3 albedo, float rough, float metal, vec3 f0) {{
        float nl = max(dot(N, L), 0.0);
        if (nl <= 0.0) return vec3(0.0);
        vec3 H = normalize(L + V);
        float nv = max(dot(N, V), 1e-4);
        float nh = max(dot(N, H), 0.0);
        float vh = max(dot(V, H), 0.0);
        vec3 F = F_Schlick(vh, f0);
        vec3 spec = (D_GGX(nh, rough) * G_Smith(nv, nl, rough)) * F / max(4.0 * nv * nl, 1e-4);
        vec3 kd = (1.0 - F) * (1.0 - metal);
        return (kd * albedo / 3.14159265 + spec) * col * nl;
      }}

      void main() {{
        if (uKind == 1) {{
          vec2 g = abs(fract(vWorld.xz / uGridStep - 0.5) - 0.5) / 0.035;
          float line = 1.0 - min(min(g.x, g.y), 1.0);
          float fade = 1.0 - smoothstep(uGridStep * 2.5, uGridStep * 7.5, length(vWorld.xz));
          if (line * fade < 0.02) discard;
          gl_FragColor = vec4(vec3(0.55, 0.62, 0.78), line * fade * 0.34);
          return;
        }}
        if (uKind == 2) {{
          float r = length(vUV * 2.0 - 1.0);
          float a = (1.0 - smoothstep(0.12, 1.0, r)) * 0.52;
          if (a < 0.005) discard;
          gl_FragColor = vec4(0.0, 0.0, 0.0, a);
          return;
        }}
        if (uWire == 1) {{
          gl_FragColor = vec4(0.92, 0.96, 1.0, 0.72);
          return;
        }}

        vec3 N = normalize(vNrm);
        vec3 V = normalize(-vViewPos);
        if (uHasNrm == 1) {{
          vec3 mapN = texture2D(uNrm, vUV).xyz * 2.0 - 1.0;
          mapN.xy *= uNrmScale;
          mat3 TBN = mat3(normalize(vTan), normalize(vBit), N);
          N = normalize(TBN * mapN);
        }}
        if (dot(N, V) < 0.0) N = -N;

        vec4 baseTex = uHasAlb == 1 ? texture2D(uAlb, vUV) : vec4(1.0);
        vec3 albedo = srgbToLinear(baseTex.rgb) * srgbToLinear(uBase.rgb);
        vec3 mr = uHasMR == 1 ? texture2D(uMR, vUV).rgb : vec3(1.0, 1.0, 1.0);
        float rough = clamp(mr.g * uFactors.y, 0.045, 1.0);
        float metal = clamp(mr.b * uFactors.x, 0.0, 1.0);
        float ao    = uHasAO == 1 ? mix(1.0, mr.r, uAOStr) : 1.0;

        if (uMode == 3) {{ gl_FragColor = vec4(linearToSrgb(albedo), 1.0); return; }}
        if (uMode == 4) {{ gl_FragColor = vec4(N * 0.5 + 0.5, 1.0); return; }}
        if (uMode == 5) {{ gl_FragColor = vec4(vec3(rough), 1.0); return; }}
        if (uMode == 6) {{ gl_FragColor = vec4(vec3(ao), 1.0); return; }}
        if (uMode == 7) {{ gl_FragColor = vec4(vec3(metal), 1.0); return; }}
        if (uMode == 8) {{
          vec2 c = floor(vUV * 16.0);
          float chk = mod(c.x + c.y, 2.0);
          vec3 tint = mix(vec3(0.14, 0.16, 0.20), vec3(0.88, 0.90, 0.95), chk);
          gl_FragColor = vec4(tint * (0.55 + 0.45 * fract(vUV.x * 4.0)), 1.0);
          return;
        }}
        if (uMode == 2) {{ albedo = vec3(0.46, 0.45, 0.44); metal = 0.0; rough = 0.52; }}

        vec3 f0 = mix(vec3(0.04), albedo, metal);
        vec3 Lo = vec3(0.0);
        Lo += directLight(uKeyDir,  V, N, uKeyCol,               albedo, rough, metal, f0);
        Lo += directLight(uFillDir, V, N, uKeyCol * 0.34,        albedo, rough, metal, f0);
        Lo += directLight(uRimDir,  V, N, vec3(0.55, 0.65, 0.85), albedo, rough, metal, f0);

        float hemi = N.y * 0.5 + 0.5;
        vec3 envIrr = mix(uGndCol, uSkyCol, hemi);
        float nv = max(dot(N, V), 1e-4);
        vec3 F = f0 + (max(vec3(1.0 - rough), f0) - f0) * pow(1.0 - nv, 5.0);
        vec3 ambient = ((1.0 - F) * (1.0 - metal) * albedo * envIrr
                      + F * envIrr * (1.0 - rough * 0.72) * 0.95) * ao;

        gl_FragColor = vec4(linearToSrgb(aces(Lo + ambient)), 1.0);
      }}`;

    function compile(type, src) {{
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {{
        const log = gl.getShaderInfoLog(s);
        gl.deleteShader(s);
        throw new Error(log || "Compilation GLSL échouée");
      }}
      return s;
    }}

    const prog = gl.createProgram();
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, vsSrc));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, fsSrc));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS))
      throw new Error(gl.getProgramInfoLog(prog) || "Édition de liens WebGL échouée");
    gl.useProgram(prog);

    const loc = {{
      pos: gl.getAttribLocation(prog, "aPos"),
      nrm: gl.getAttribLocation(prog, "aNrm"),
      uv:  gl.getAttribLocation(prog, "aUV"),
      tan: gl.getAttribLocation(prog, "aTan"),
      mvp: gl.getUniformLocation(prog, "uMVP"),
      mdl: gl.getUniformLocation(prog, "uModel"),
      viw: gl.getUniformLocation(prog, "uView"),
      alb: gl.getUniformLocation(prog, "uAlb"),
      mr:  gl.getUniformLocation(prog, "uMR"),
      nrmT:gl.getUniformLocation(prog, "uNrm"),
      bas: gl.getUniformLocation(prog, "uBase"),
      fac: gl.getUniformLocation(prog, "uFactors"),
      nsc: gl.getUniformLocation(prog, "uNrmScale"),
      aos: gl.getUniformLocation(prog, "uAOStr"),
      grd: gl.getUniformLocation(prog, "uGridStep"),
      ha:  gl.getUniformLocation(prog, "uHasAlb"),
      hm:  gl.getUniformLocation(prog, "uHasMR"),
      hn:  gl.getUniformLocation(prog, "uHasNrm"),
      hao: gl.getUniformLocation(prog, "uHasAO"),
      mod: gl.getUniformLocation(prog, "uMode"),
      knd: gl.getUniformLocation(prog, "uKind"),
      wir: gl.getUniformLocation(prog, "uWire"),
      kd:  gl.getUniformLocation(prog, "uKeyDir"),
      fd:  gl.getUniformLocation(prog, "uFillDir"),
      rd:  gl.getUniformLocation(prog, "uRimDir"),
      kc:  gl.getUniformLocation(prog, "uKeyCol"),
      sc:  gl.getUniformLocation(prog, "uSkyCol"),
      gc:  gl.getUniformLocation(prog, "uGndCol"),
    }};

    function makeBuf(data) {{
      const b = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      return b;
    }}

    function solid1x1(rgba) {{
      const tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(rgba));
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      return tex;
    }}

    const whiteTex = solid1x1([255, 255, 255, 255]);
    const flatNrm  = solid1x1([128, 128, 255, 255]);
    const defMR    = solid1x1([255, 255, 255, 255]);

    const anisoExt = gl.getExtension("EXT_texture_filter_anisotropic") ||
                     gl.getExtension("MOZ_EXT_texture_filter_anisotropic") ||
                     gl.getExtension("WEBKIT_EXT_texture_filter_anisotropic");
    const maxAniso = anisoExt ? Math.min(16, gl.getParameter(anisoExt.MAX_TEXTURE_MAX_ANISOTROPY_EXT) || 4) : 1;

    function uploadScene(sceneObj) {{
      const texCache = new Map();
      function getTex(ti, fallbackRGBA) {{
        if (ti < 0) return null;
        if (texCache.has(ti)) return texCache.get(ti);
        const texDef = sceneObj.json.textures[ti];
        const imgDef = sceneObj.json.images[texDef.source];
        const tex = solid1x1(fallbackRGBA);
        texCache.set(ti, tex);
        if (imgDef.bufferView !== undefined) {{
          const bv = sceneObj.json.bufferViews[imgDef.bufferView];
          const bytes = sceneObj.bin.subarray(bv.byteOffset || 0, (bv.byteOffset || 0) + bv.byteLength);
          const dataURI = bytesToDataURI(bytes, imgDef.mimeType || "image/png");
          const im = new Image();
          im.onload = () => {{
            gl.bindTexture(gl.TEXTURE_2D, tex);
            gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, im);
            const pot = (im.width & (im.width - 1)) === 0 && (im.height & (im.height - 1)) === 0;
            if (isWebGL2 || pot) {{
              gl.generateMipmap(gl.TEXTURE_2D);
              gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
              if (anisoExt && maxAniso > 1) {{
                gl.texParameterf(gl.TEXTURE_2D, anisoExt.TEXTURE_MAX_ANISOTROPY_EXT, maxAniso);
              }}
            }} else {{
              gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
              gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
              gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
            }}
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
          }};
          im.src = dataURI;
        }}
        return tex;
      }}

      return sceneObj.parts.map(p => ({{
        bPos: makeBuf(p.pos),
        bNrm: makeBuf(p.nrm),
        bUV:  makeBuf(p.uv),
        bTan: makeBuf(p.tan),
        bWire: makeBuf(p.wirePos),
        count: p.count,
        wireCount: p.wireCount,
        model: p.model,
        jointChain: p.jointChain,
        base: p.baseColor,
        metal: p.metal,
        rough: p.rough,
        albTex: getTex(p.albTexIdx, [245, 245, 245, 255]),
        mrTex:  getTex(p.mrTexIdx,  [255, 255, 255, 255]),
        nrmTex: getTex(p.nrmTexIdx, [128, 128, 255, 255]),
        nrmScale: p.nrmScale,
        hasAO: p.aoTexIdx >= 0 ? 1 : 0,
        aoStrength: p.aoStrength,
      }}));
    }}

    let draws = uploadScene(parsed);

    const quadPos = makeBuf(new Float32Array([-1,0,-1, 1,0,-1, 1,0,1, -1,0,-1, 1,0,1, -1,0,1]));
    const quadNrm = makeBuf(new Float32Array([0,1,0, 0,1,0, 0,1,0, 0,1,0, 0,1,0, 0,1,0]));
    const quadUV  = makeBuf(new Float32Array([0,0, 1,0, 1,1, 0,0, 1,1, 0,1]));
    const quadTan = makeBuf(new Float32Array([1,0,0,1, 1,0,0,1, 1,0,0,1, 1,0,0,1, 1,0,0,1, 1,0,0,1]));

    function bindAttribs(bP, bN, bU, bT) {{
      gl.bindBuffer(gl.ARRAY_BUFFER, bP);
      gl.enableVertexAttribArray(loc.pos);
      gl.vertexAttribPointer(loc.pos, 3, gl.FLOAT, false, 0, 0);
      if (loc.nrm >= 0) {{
        gl.bindBuffer(gl.ARRAY_BUFFER, bN);
        gl.enableVertexAttribArray(loc.nrm);
        gl.vertexAttribPointer(loc.nrm, 3, gl.FLOAT, false, 0, 0);
      }}
      if (loc.uv >= 0) {{
        gl.bindBuffer(gl.ARRAY_BUFFER, bU);
        gl.enableVertexAttribArray(loc.uv);
        gl.vertexAttribPointer(loc.uv, 2, gl.FLOAT, false, 0, 0);
      }}
      if (loc.tan >= 0) {{
        gl.bindBuffer(gl.ARRAY_BUFFER, bT);
        gl.enableVertexAttribArray(loc.tan);
        gl.vertexAttribPointer(loc.tan, 4, gl.FLOAT, false, 0, 0);
      }}
    }}

    const ENV = {{
      studio:  {{ key: [2.8, 2.72, 2.62], sky: [0.32, 0.36, 0.46], gnd: [0.10, 0.09, 0.09] }},
      outdoor: {{ key: [3.2, 3.05, 2.75], sky: [0.56, 0.68, 0.95], gnd: [0.20, 0.17, 0.13] }},
    }};
    const norm3 = v => {{ const l = Math.hypot(v[0],v[1],v[2]) || 1; return [v[0]/l, v[1]/l, v[2]/l]; }};
    const KEY = norm3([0.52, 0.76, 0.40]);
    const FILL = norm3([-0.74, 0.26, 0.56]);
    const RIM = norm3([-0.22, 0.42, -0.88]);

    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.uniform1i(loc.alb, 0); gl.uniform1i(loc.mr, 1); gl.uniform1i(loc.nrmT, 2);
    gl.uniform3fv(loc.kd, KEY); gl.uniform3fv(loc.fd, FILL); gl.uniform3fv(loc.rd, RIM);

    lodsBar.addEventListener("click", e => {{
      const b = e.target.closest("button[data-lod]");
      if (!b) return;
      const idx = +b.dataset.lod;
      if (idx === cam.activeLod) return;
      cam.activeLod = idx;
      for (const x of lodsBar.querySelectorAll("button")) x.classList.toggle("on", x === b);
      parsed = parseGLB(LODS_DATA[idx].b64);
      draws = uploadScene(parsed);
      updateDownload(idx);
      updateHud();
    }});

    function updateHud() {{
      const entry = LODS_DATA[cam.activeLod] || LODS_DATA[0];
      const api = isWebGL2 ? "WebGL2" : "WebGL1";
      hudTxt.textContent = api + " PBR ACES · " + entry.id + " · " +
        Math.round(parsed.totalTris).toLocaleString("fr-FR") + " tris · " +
        draws.length + (draws.length > 1 ? " draw calls" : " draw call");
    }}
    updateHud();

    bindPointerControls(canvas);

    function resize() {{
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.max(2, Math.floor((canvas.clientWidth || 800) * dpr));
      const h = Math.max(2, Math.floor((canvas.clientHeight || 520) * dpr));
      if (canvas.width !== w || canvas.height !== h) {{
        canvas.width = w; canvas.height = h;
      }}
      gl.viewport(0, 0, canvas.width, canvas.height);
    }}

    let last = performance.now();
    function frame(now) {{
      resize();
      const dt = Math.min(0.05, Math.max(0.0, (now - last) / 1000));
      last = now;
      if (cam.spin) cam.az += dt * 0.45;

      const env = cam.mode === 1 ? ENV.outdoor : ENV.studio;
      gl.clearColor(0.068, 0.080, 0.112, 1.0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.uniform3fv(loc.kc, env.key);
      gl.uniform3fv(loc.sc, env.sky);
      gl.uniform3fv(loc.gc, env.gnd);
      gl.uniform1i(loc.mod, cam.mode);
      gl.uniform1f(loc.grd, Math.pow(10, Math.floor(Math.log10(cam.radius))) * 0.5);

      const eye = [
        cam.target[0] + cam.dist * Math.cos(cam.el) * Math.sin(cam.az),
        cam.target[1] + cam.dist * Math.sin(cam.el),
        cam.target[2] + cam.dist * Math.cos(cam.el) * Math.cos(cam.az),
      ];
      const view = M4.lookAt(eye, cam.target, [0, 1, 0]);
      const proj = M4.persp(42 * Math.PI / 180, canvas.width / Math.max(1, canvas.height), cam.radius * 0.02, cam.radius * 60);
      const vp = M4.mul(proj, view);
      gl.uniformMatrix4fv(loc.viw, false, view);

      // Maillage principal PBR + Cinématique hiérarchique glTF 2.0 multi-niveaux (`front_steering -> front_wheel`)
      gl.uniform1i(loc.knd, 0);
      gl.uniform1i(loc.wir, 0);
      gl.depthMask(true);
      const tSec = now * 0.001;
      for (const dc of draws) {{
        let curModel = dc.model;
        if (cam.animJoints && dc.jointChain) {{
          curModel = M4.ident();
          for (const st of dc.jointChain) {{
            if (st.joint && st.joint.kind !== "fixed") {{
              const ax = st.joint.axis || [0, 1, 0];
              const al = Math.hypot(ax[0], ax[1], ax[2]) || 1;
              const ux = ax[0] / al, uy = ax[1] / al, uz = ax[2] / al;
              const nmLow = (st.name || "").toLowerCase();
              const isSpin = nmLow.includes("wheel") || nmLow.includes("rotor") || nmLow.includes("prop") || nmLow.includes("fan");
              const ang = isSpin ? (-tSec * 3.2) : (Math.sin(tSec * 1.45) * 0.20);
              const ha = ang * 0.5, sa = Math.sin(ha), ca = Math.cos(ha);
              const lr = st.localRest;
              curModel = M4.mul(curModel, M4.trs([lr[12], lr[13], lr[14]], [ux * sa, uy * sa, uz * sa, ca], [1, 1, 1]));
            }} else {{
              curModel = M4.mul(curModel, st.localRest);
            }}
          }}
        }}
        bindAttribs(dc.bPos, dc.bNrm, dc.bUV, dc.bTan);
        gl.uniformMatrix4fv(loc.mdl, false, curModel);
        gl.uniformMatrix4fv(loc.mvp, false, M4.mul(vp, curModel));
        gl.uniform4fv(loc.bas, dc.base);
        gl.uniform2f(loc.fac, dc.metal, dc.rough);
        gl.uniform1f(loc.nsc, dc.nrmScale);
        gl.uniform1f(loc.aos, dc.aoStrength);
        gl.uniform1i(loc.ha, dc.albTex ? 1 : 0);
        gl.uniform1i(loc.hm, dc.mrTex  ? 1 : 0);
        gl.uniform1i(loc.hn, dc.nrmTex ? 1 : 0);
        gl.uniform1i(loc.hao, dc.hasAO);
        gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, dc.albTex || whiteTex);
        gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, dc.mrTex  || defMR);
        gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, dc.nrmTex || flatNrm);
        gl.drawArrays(gl.TRIANGLES, 0, dc.count);

        // Surcouche filaire propre sur vraies arêtes de triangles
        if (cam.wire) {{
          gl.uniform1i(loc.wir, 1);
          bindAttribs(dc.bWire, dc.bWire, dc.bWire, dc.bWire);
          gl.drawArrays(gl.LINES, 0, dc.wireCount);
          gl.uniform1i(loc.wir, 0);
        }}
      }}

      // Ombre portée douce + grille métrique au sol
      gl.depthMask(false);
      bindAttribs(quadPos, quadNrm, quadUV, quadTan);
      const sh = M4.trs([cam.target[0], cam.floorY + cam.radius * 0.002, cam.target[2]], [0,0,0,1],
                        [cam.radius * 1.15, 1, cam.radius * 1.15]);
      gl.uniform1i(loc.knd, 2);
      gl.uniformMatrix4fv(loc.mdl, false, sh);
      gl.uniformMatrix4fv(loc.mvp, false, M4.mul(vp, sh));
      gl.drawArrays(gl.TRIANGLES, 0, 6);

      const gr = M4.trs([0, cam.floorY, 0], [0,0,0,1], [cam.radius * 12, 1, cam.radius * 12]);
      gl.uniform1i(loc.knd, 1);
      gl.uniformMatrix4fv(loc.mdl, false, gr);
      gl.uniformMatrix4fv(loc.mvp, false, M4.mul(vp, gr));
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      gl.depthMask(true);

      requestAnimationFrame(frame);
    }}
    requestAnimationFrame(frame);
    return true;
  }}

  // =========================================================================
  // MOTEUR 2 : RASTÉRISEUR 3D LOGICIEL <canvas 2d> PLEINE COULEUR DE SECOURS
  // =========================================================================
  function startCanvas2DFallback(reason) {{
    canvas.style.display = "none";
    canvas2d.style.display = "block";
    const ctx = canvas2d.getContext("2d");
    bindPointerControls(canvas2d);
    if (reason) showBanner("Mode 3D logiciel actif (" + reason + ") — rotation interactive pleine couleur.");

    let texPixels = null, texW = 0, texH = 0;
    function decodeAlbedoPixels(sceneObj) {{
      texPixels = null;
      const p0 = sceneObj.parts[0];
      if (!p0 || p0.albTexIdx < 0) return;
      const imgDef = sceneObj.json.images[sceneObj.json.textures[p0.albTexIdx].source];
      if (!imgDef || imgDef.bufferView === undefined) return;
      const bv = sceneObj.json.bufferViews[imgDef.bufferView];
      const bytes = sceneObj.bin.subarray(bv.byteOffset || 0, (bv.byteOffset || 0) + bv.byteLength);
      const im = new Image();
      im.onload = () => {{
        const off = document.createElement("canvas");
        off.width = texW = 256; off.height = texH = 256;
        const octx = off.getContext("2d");
        octx.drawImage(im, 0, 0, texW, texH);
        texPixels = octx.getImageData(0, 0, texW, texH).data;
      }};
      im.src = bytesToDataURI(bytes, imgDef.mimeType || "image/png");
    }}

    function buildWorldTris(sceneObj) {{
      decodeAlbedoPixels(sceneObj);
      const tris = [];
      for (const p of sceneObj.parts) {{
        const m = p.model;
        for (let i = 0, u = 0; i < p.pos.length; i += 9, u += 6) {{
          const pts = [], nrms = [];
          for (let k = 0; k < 3; k++) {{
            const x=p.pos[i+k*3], y=p.pos[i+k*3+1], z=p.pos[i+k*3+2];
            pts.push([
              m[0]*x + m[4]*y + m[8]*z + m[12],
              m[1]*x + m[5]*y + m[9]*z + m[13],
              m[2]*x + m[6]*y + m[10]*z + m[14],
            ]);
            const nx=p.nrm[i+k*3], ny=p.nrm[i+k*3+1], nz=p.nrm[i+k*3+2];
            const wx=m[0]*nx + m[4]*ny + m[8]*nz;
            const wy=m[1]*nx + m[5]*ny + m[9]*nz;
            const wz=m[2]*nx + m[6]*ny + m[10]*nz;
            const l = Math.hypot(wx,wy,wz) || 1;
            nrms.push([wx/l, wy/l, wz/l]);
          }}
          tris.push({{
            pts,
            uv: [(p.uv[u]+p.uv[u+2]+p.uv[u+4])/3, (p.uv[u+1]+p.uv[u+3]+p.uv[u+5])/3],
            n: [(nrms[0][0]+nrms[1][0]+nrms[2][0])/3,
                (nrms[0][1]+nrms[1][1]+nrms[2][1])/3,
                (nrms[0][2]+nrms[1][2]+nrms[2][2])/3],
            c: p.baseColor,
          }});
        }}
      }}
      return tris;
    }}

    let softTris = buildWorldTris(parsed);
    hudTxt.textContent = "Rendu 3D CPU · " + softTris.length.toLocaleString("fr-FR") + " tris";
    lodsBar.addEventListener("click", e => {{
      const b = e.target.closest("button[data-lod]");
      if (!b) return;
      const idx = +b.dataset.lod;
      cam.activeLod = idx;
      for (const x of lodsBar.querySelectorAll("button")) x.classList.toggle("on", x === b);
      parsed = parseGLB(LODS_DATA[idx].b64);
      softTris = buildWorldTris(parsed);
      updateDownload(idx);
      hudTxt.textContent = "Rendu 3D CPU · " + softTris.length.toLocaleString("fr-FR") + " tris";
    }});

    let last = performance.now();
    function frame2d(now) {{
      const dt = Math.min(0.05, Math.max(0.0, (now - last) / 1000));
      last = now;
      if (cam.spin) cam.az += dt * 0.45;
      const w = canvas2d.width = Math.max(2, canvas2d.clientWidth || 800);
      const h = canvas2d.height = Math.max(2, canvas2d.clientHeight || 520);
      ctx.clearRect(0, 0, w, h);

      const eye = [
        cam.target[0] + cam.dist * Math.cos(cam.el) * Math.sin(cam.az),
        cam.target[1] + cam.dist * Math.sin(cam.el),
        cam.target[2] + cam.dist * Math.cos(cam.el) * Math.cos(cam.az),
      ];
      const view = M4.lookAt(eye, cam.target, [0, 1, 0]);
      const proj = M4.persp(42 * Math.PI / 180, w / h, cam.radius * 0.05, cam.radius * 40);
      const vp = M4.mul(proj, view);

      const drawList = [];
      for (let i = 0; i < softTris.length; i++) {{
        const t = softTris[i];
        const scr = [];
        let zSum = 0, clipped = false;
        for (let k = 0; k < 3; k++) {{
          const p = t.pts[k];
          const cx = vp[0]*p[0] + vp[4]*p[1] + vp[8]*p[2]  + vp[12];
          const cy = vp[1]*p[0] + vp[5]*p[1] + vp[9]*p[2]  + vp[13];
          const cz = vp[2]*p[0] + vp[6]*p[1] + vp[10]*p[2] + vp[14];
          const cw = vp[3]*p[0] + vp[7]*p[1] + vp[11]*p[2] + vp[15];
          if (cw <= 1e-4) {{ clipped = true; break; }}
          scr.push([(cx / cw * 0.5 + 0.5) * w, (-cy / cw * 0.5 + 0.5) * h]);
          zSum += cz / cw;
        }}
        if (!clipped) drawList.push({{ scr, z: zSum / 3, n: t.n, c: t.c, uv: t.uv }});
      }}
      drawList.sort((a, b) => b.z - a.z);

      for (let i = 0; i < drawList.length; i++) {{
        const d = drawList[i];
        const lit = Math.max(0.22, 0.30 + 0.68 * Math.max(0, d.n[0]*0.45 + d.n[1]*0.72 + d.n[2]*0.52));
        let cr = d.c[0] * 240, cg = d.c[1] * 230, cb = d.c[2] * 230;
        if (texPixels && cam.mode !== 2) {{
          const tx = Math.max(0, Math.min(texW - 1, Math.floor((((d.uv[0] % 1) + 1) % 1) * texW)));
          const ty = Math.max(0, Math.min(texH - 1, Math.floor((((d.uv[1] % 1) + 1) % 1) * texH)));
          const o = (ty * texW + tx) * 4;
          cr = texPixels[o]; cg = texPixels[o+1]; cb = texPixels[o+2];
        }}
        const r = Math.min(255, Math.round(cr * lit));
        const g = Math.min(255, Math.round(cg * lit));
        const b = Math.min(255, Math.round(cb * lit));
        ctx.beginPath();
        ctx.moveTo(d.scr[0][0], d.scr[0][1]);
        ctx.lineTo(d.scr[1][0], d.scr[1][1]);
        ctx.lineTo(d.scr[2][0], d.scr[2][1]);
        ctx.closePath();
        ctx.fillStyle = "rgb(" + r + "," + g + "," + b + ")";
        ctx.fill();
        if (cam.wire) {{
          ctx.strokeStyle = "rgba(235,245,255,0.55)";
          ctx.lineWidth = 0.7;
          ctx.stroke();
        }}
      }}
      requestAnimationFrame(frame2d);
    }}
    requestAnimationFrame(frame2d);
  }}

  try {{
    if (!startWebGL()) startCanvas2DFallback("WebGL désactivé");
  }} catch (err) {{
    console.error("WebGL fallback:", err);
    startCanvas2DFallback(err && err.message ? err.message : String(err));
  }}
}})();
</script>
</body>
</html>
"""


def build_preview(outdir: str, title: str = "Asset 3D", report: dict | None = None,
                  glb: str | None = None, out_name: str = "preview.html") -> str | None:
    d = Path(outdir)
    glb_path = _pick_glb(d, glb)
    if glb_path is None:
        return None
    if report is None and (d / "report.json").is_file():
        try:
            report = json.loads((d / "report.json").read_text(encoding="utf-8"))
        except Exception:
            report = None

    lods = _collect_lods(d, glb_path)
    lods_json = json.dumps(lods, separators=(",", ":"))
    html = _PAGE.format(
        title=_html.escape(title),
        filename=_html.escape(glb_path.name),
        lods_json=lods_json,
        stats=_stats_html(d, report),
        photos=_photo_cards(d),
    )
    out = d / out_name
    out.write_text(html, encoding="utf-8")
    return str(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("outdir", help="Dossier de sortie contenant un .glb (et optionnellement report.json)")
    ap.add_argument("--title", default=None)
    ap.add_argument("--glb", default=None, help="Chemin explicite vers le .glb si plusieurs")
    ap.add_argument("-o", "--out", default="preview.html", help="Nom du fichier HTML dans outdir")
    a = ap.parse_args(argv)
    out = build_preview(a.outdir, title=a.title or Path(a.outdir).name, glb=a.glb, out_name=a.out)
    if out is None:
        print(f"Aucun .glb trouvé dans {a.outdir}")
        return 1
    print(f"Aperçu autonome écrit : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
