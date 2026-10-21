#!/usr/bin/env python3
"""preview.py — preview HTML 100 % autonome (hors-ligne) d'une génération 3d-forge.

Produit un unique `preview.html` auto-portant dans le dossier de sortie :
  * Viewer WebGL PBR embarqué en pur JS vanilla (zéro dépendance CDN externe,
    fonctionne 100 % hors connexion dès le double-clic !) qui décode directement
    le binaire `.glb` embarqué en base64 (géométrie multi-parties, hiérarchie de
    nœuds, `baseColorTexture`, `metallicRoughnessTexture`, `normalTexture`,
    transparence, éclairage studio 3 points ACES, grille au sol, orbite/zoom/pan,
    rotation auto, mode filaire, préréglages caméra).
  * Bouton de téléchargement direct du `.glb` depuis la page.
  * Bandeau des photos de la génération + métriques QA du `report.json`.
"""
from __future__ import annotations

import argparse
import base64
import glob
import io
import json
import os
import sys

PHOTO_PREFS = [
    ("qa_game_sheet.png", "planche QA studio PBR"),
    ("*_trois_quarts.png", "vue 3/4"),
    ("*_three_quarter.png", "vue 3/4"),
    ("*_all_faces.png", "les 6 faces"),
    ("*_turntable.png", "turntable"),
    ("*_references.png", "références (Stage 0)"),
    ("*_front.png", "face"),
    ("*_face.png", "face"),
]
MAX_PHOTOS = 4


def _b64(path: str) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def _yup_glb_b64(glb_path: str) -> str:
    """Charge le GLB, tourne Z-up -> Y-up (-90° X) et ré-exporte en base64."""
    import numpy as np
    import trimesh

    scene = trimesh.load(glb_path, force="scene")
    rot = trimesh.transformations.rotation_matrix(-np.pi / 2.0, [1, 0, 0])
    scene.apply_transform(rot)
    buf = io.BytesIO()
    scene.export(buf, file_type="glb")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def find_glb(outdir: str) -> str | None:
    glbs = sorted(glob.glob(os.path.join(outdir, "*.glb")))
    return glbs[0] if glbs else None


def find_photos(outdir: str) -> list[tuple[str, str]]:
    seen, photos = set(), []
    for pattern, label in PHOTO_PREFS:
        for p in sorted(glob.glob(os.path.join(outdir, pattern))):
            ap = os.path.abspath(p)
            if ap not in seen:
                seen.add(ap)
                photos.append((ap, label))
    return photos[:MAX_PHOTOS]


def _stats_html(report: dict | None) -> str:
    if not report:
        return ""
    chips = []
    v = report.get("validation") or report.get("stats") or {}
    tri = v.get("triangles") or v.get("triangle_count")
    if tri:
        chips.append(f"{tri:,} triangles".replace(",", " "))
    wt = v.get("watertight") if "watertight" in v else v.get("watertight_union")
    if wt is not None:
        chips.append("étanche ✓" if wt else "non étanche ⚠")
    coh = (report.get("coherence") or {}).get("mean")
    if coh:
        chips.append(f"IoU {coh}")
    parts = (report.get("stats") or {}).get("parts")
    if parts and parts > 1:
        chips.append(f"{parts} parties")
    dur = report.get("duration_s")
    if dur:
        chips.append(f"{dur}s")
    return ("<div class='chips'>" + "".join(f"<span>{c}</span>" for c in chips) + "</div>") if chips else ""


def build_preview(outdir: str, title: str | None = None, glb: str | None = None,
                  report: dict | None = None, out_name: str = "preview.html",
                  quiet: bool = False) -> str | None:
    """Écrit `<outdir>/preview.html` 100 % autonome hors-ligne et retourne son chemin."""
    outdir = os.path.abspath(outdir)
    glb = glb or find_glb(outdir)
    if not glb or not os.path.isfile(glb):
        if not quiet:
            print("[preview] aucun GLB trouvé, preview sautée", file=sys.stderr)
        return None
    if report is None:
        rp = os.path.join(outdir, "report.json")
        if os.path.isfile(rp):
            try:
                with open(rp) as fh:
                    report = json.load(fh)
            except Exception:
                report = None
    title = title or os.path.basename((report or {}).get("output_dir", outdir))
    photos = find_photos(outdir)

    photo_html = ""
    if photos:
        cells = "".join(
            f"<figure><img src='data:image/png;base64,{_b64(p)}' alt='{lab}' "
            f"loading='lazy'><figcaption>{lab}</figcaption></figure>"
            for p, lab in photos)
        photo_html = f"<section id='shots'><h2>Photos de contrôle</h2>{cells}</section>"

    glb_name = os.path.basename(glb)
    glb_b64 = _yup_glb_b64(glb)
    html = _TEMPLATE.format(
        title=title,
        glb_name=glb_name,
        glb_b64=glb_b64,
        stats=_stats_html(report),
        photos=photo_html,
    )
    out_path = os.path.join(outdir, out_name)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out_path


_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — 3d-forge offline WebGL viewer</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #101014; color: #e8e6e3; font: 15px/1.5 system-ui, -apple-system, sans-serif; }}
  header {{ padding: 16px 24px 10px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
  h1 {{ font-size: 19px; font-weight: 650; }}
  .badge {{ font-size: 11px; letter-spacing: .12em; text-transform: uppercase;
           color: #d4b872; border: 1px solid #3f3828; border-radius: 999px; padding: 2px 10px; }}
  #stage-wrap {{ position: relative; width: 100%; height: min(72vh, 760px);
                background: radial-gradient(1100px 520px at 50% 18%, #252630, #0d0d12);
                border-top: 1px solid #22222a; border-bottom: 1px solid #22222a; overflow: hidden; }}
  canvas {{ width: 100%; height: 100%; display: block; cursor: grab; touch-action: none; }}
  canvas:active {{ cursor: grabbing; }}
  #hint {{ position: absolute; right: 16px; bottom: 12px; font-size: 11px; color: #8c8a84;
          background: rgba(16,16,20,.72); padding: 4px 10px; border-radius: 999px; pointer-events: none; }}
  #err {{ position: absolute; inset: 20px; display: none; align-items: center; justify-content: center;
         color: #e6c387; font-size: 14px; text-align: center; }}
  .tools {{ display: flex; gap: 8px; padding: 12px 24px 0; align-items: center; flex-wrap: wrap; }}
  button, select, a.dl {{ background: #1c1d24; color: #e8e6e3; border: 1px solid #32333e; text-decoration: none;
                 border-radius: 8px; padding: 6px 12px; cursor: pointer; font-size: 13px; }}
  button:hover, select:hover, a.dl:hover {{ background: #272833; border-color: #4a4c5c; }}
  .chips {{ display: flex; gap: 8px; flex-wrap: wrap; padding: 12px 24px 0; }}
  .chips span {{ font-size: 12px; color: #b9b7b2; background: #191920;
                border: 1px solid #2b2b34; border-radius: 999px; padding: 3px 10px; }}
  #shots {{ padding: 18px 24px 32px; }}
  #shots h2 {{ font-size: 13px; font-weight: 600; color: #a9a7a2; margin-bottom: 10px;
              text-transform: uppercase; letter-spacing: .1em; }}
  #shots figure {{ display: inline-block; margin: 0 10px 10px 0; vertical-align: top; }}
  #shots img {{ max-height: 220px; border-radius: 10px; border: 1px solid #2c2c34; display: block; }}
  #shots figcaption {{ font-size: 11px; color: #8d8b86; margin-top: 5px; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <span class="badge">3d-forge · 100% hors-ligne</span>
</header>

<div id="stage-wrap">
  <canvas id="glcanvas"></canvas>
  <div id="err"></div>
  <div id="hint">Clic gauche : orbite · Clic droit / Maj : pan · Molette : zoom</div>
</div>

<div class="tools">
  <button id="rot">⏸ rotation</button>
  <button id="v34">🎥 vue 3/4</button>
  <button id="vfront">face</button>
  <button id="vside">profil</button>
  <button id="vtop">dessus</button>
  <button id="animBtn" style="display:none">⚙ animer articulations</button>
  <select id="envSel" title="Environnement HDRI">
    <option value="0">💡 Studio Photo</option>
    <option value="1">🔥 Atelier Chaud</option>
    <option value="2">☀ Soleil Extérieur</option>
    <option value="3">🌙 Nuit Cyber</option>
  </select>
  <select id="chanSel" title="Canal d'inspection technique">
    <option value="0">🎨 Rendu PBR Complet</option>
    <option value="1">🖼 Albédo (BaseColor)</option>
    <option value="2">✨ Roughness (Rugosité)</option>
    <option value="3">🔩 Metallic</option>
    <option value="4">🧭 Normal Map</option>
    <option value="5">🌑 Ambient Occlusion</option>
    <option value="6">◇ Filaire (Wireframe)</option>
  </select>
  <a class="dl" id="dl" download="{glb_name}">⬇ télécharger {glb_name}</a>
</div>

{stats}
{photos}

<script>
(() => {{
  const GLB_B64 = "{glb_b64}";
  const binStr = atob(GLB_B64);
  const bytes = new Uint8Array(binStr.length);
  for (let i = 0; i < binStr.length; i++) bytes[i] = binStr.charCodeAt(i);
  const glbBlob = new Blob([bytes], {{ type: "model/gltf-binary" }});
  document.getElementById("dl").href = URL.createObjectURL(glbBlob);

  const canvas = document.getElementById("glcanvas");
  const gl = canvas.getContext("webgl2", {{ antialias: true, alpha: true }})
          || canvas.getContext("webgl", {{ antialias: true, alpha: true }});
  const showErr = (msg) => {{
    const el = document.getElementById("err");
    el.textContent = msg; el.style.display = "flex";
  }};
  if (!gl) {{ showErr("WebGL indisponible dans ce navigateur — consultez les photos ci-dessous."); return; }}
  gl.getExtension("OES_standard_derivatives");

  // --- Matrices 4x4 (colonne-major WebGL) ---
  const m4Identity = () => new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]);
  function m4Mul(a, b) {{
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++)
      for (let r = 0; r < 4; r++)
        o[c*4+r] = a[r]*b[c*4] + a[4+r]*b[c*4+1] + a[8+r]*b[c*4+2] + a[12+r]*b[c*4+3];
    return o;
  }}
  function m4TRS(t, q, s) {{
    const [x,y,z,w] = q;
    const x2=x+x, y2=y+y, z2=z+z;
    const xx=x*x2, xy=x*y2, xz=x*z2, yy=y*y2, yz=y*z2, zz=z*z2;
    const wx=w*x2, wy=w*y2, wz=w*z2;
    const m = new Float32Array(16);
    m[0]=(1-(yy+zz))*s[0]; m[1]=(xy+wz)*s[0];     m[2]=(xz-wy)*s[0];     m[3]=0;
    m[4]=(xy-wz)*s[1];     m[5]=(1-(xx+zz))*s[1]; m[6]=(yz+wx)*s[1];     m[7]=0;
    m[8]=(xz+wy)*s[2];     m[9]=(yz-wx)*s[2];     m[10]=(1-(xx+yy))*s[2];m[11]=0;
    m[12]=t[0]; m[13]=t[1]; m[14]=t[2]; m[15]=1;
    return m;
  }}
  function m4Persp(fov, aspect, near, far) {{
    const f = 1 / Math.tan(fov / 2), nf = 1 / (near - far);
    return new Float32Array([f/aspect,0,0,0, 0,f,0,0, 0,0,(far+near)*nf,-1, 0,0,2*far*near*nf,0]);
  }}
  function m4LookAt(e, c, up) {{
    let zx=e[0]-c[0], zy=e[1]-c[1], zz=e[2]-c[2];
    let zl = Math.hypot(zx,zy,zz) || 1; zx/=zl; zy/=zl; zz/=zl;
    let xx = up[1]*zz - up[2]*zy, xy = up[2]*zx - up[0]*zz, xz = up[0]*zy - up[1]*zx;
    let xl = Math.hypot(xx,xy,xz);
    if (xl < 1e-6) {{ xx=1; xy=0; xz=0; xl=1; }}
    xx/=xl; xy/=xl; xz/=xl;
    const yx = zy*xz - zz*xy, yy = zz*xx - zx*xz, yz = zx*xy - zy*xx;
    return new Float32Array([
      xx, yx, zx, 0,
      xy, yy, zy, 0,
      xz, yz, zz, 0,
      -(xx*e[0]+xy*e[1]+xz*e[2]), -(yx*e[0]+yy*e[1]+yz*e[2]), -(zx*e[0]+zy*e[1]+zz*e[2]), 1
    ]);
  }}

  // --- Shaders PBR Studio ACES ---
  const vsSrc = `
    attribute vec3 aPos;
    attribute vec3 aNrm;
    attribute vec2 aUV;
    uniform mat4 uMVP, uModel, uView;
    varying vec3 vNrm;
    varying vec3 vViewPos;
    varying vec2 vUV;
    void main() {{
      vec4 wp = uModel * vec4(aPos, 1.0);
      vec4 vp = uView * wp;
      vViewPos = vp.xyz;
      vNrm = mat3(uView) * mat3(uModel) * aNrm;
      vUV = aUV;
      gl_Position = uMVP * vec4(aPos, 1.0);
    }}`;
  const fsSrc = `
    #ifdef GL_OES_standard_derivatives
    #extension GL_OES_standard_derivatives : enable
    #endif
    precision highp float;
    varying vec3 vNrm;
    varying vec3 vViewPos;
    varying vec2 vUV;
    uniform vec4 uBaseCol;
    uniform vec3 uEmissive;
    uniform float uMetal, uRough;
    uniform int uEnv, uChan;
    uniform bool uHasAlb, uHasMR, uHasNrm, uWire;
    uniform sampler2D uAlbTex, uMRTex, uNrmTex;

    vec3 aces(vec3 x) {{
      vec3 m = clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
      return pow(m, vec3(1.0 / 2.2));
    }}
    vec3 studioHDRI(vec3 d, float r) {{
      if (uEnv == 1) {{
        // Atelier chaud forgé / ambre
        float hz = 1.0 / (1.0 + exp(d.y * 6.5));
        vec3 env = mix(vec3(0.08, 0.055, 0.042), vec3(0.24, 0.19, 0.15), hz);
        vec3 k1 = normalize(vec3(0.45, 0.80, 0.40)), k2 = normalize(vec3(-0.75, 0.35, 0.55));
        float w1 = 0.34 + 1.3 * r, w2 = 0.25 + 1.3 * r;
        env += vec3(4.1, 3.1, 2.1) * exp(-max(0.0, 2.0*(1.0-dot(d,k1)))/(w1*w1)) * pow(0.34/w1, 1.35);
        env += vec3(1.5, 1.7, 2.2) * exp(-max(0.0, 2.0*(1.0-dot(d,k2)))/(w2*w2)) * pow(0.25/w2, 1.35);
        return env;
      }}
      if (uEnv == 2) {{
        // Soleil extérieur ciel bleu + rebond sable
        vec3 sky = mix(vec3(0.34, 0.46, 0.72), vec3(0.14, 0.28, 0.68), clamp(d.y, 0.0, 1.0));
        vec3 gnd = vec3(0.28, 0.25, 0.21);
        vec3 env = mix(gnd, sky, smoothstep(-0.08, 0.12, d.y));
        vec3 sun = normalize(vec3(0.52, 0.74, 0.42));
        float ws = 0.14 + 1.35 * r;
        env += vec3(6.2, 5.7, 4.9) * exp(-max(0.0, 2.0*(1.0-dot(d,sun)))/(ws*ws)) * pow(0.14/ws, 1.45);
        return env;
      }}
      if (uEnv == 3) {{
        // Nuit cyber néon cyan / magenta
        vec3 env = vec3(0.02, 0.025, 0.045);
        vec3 c1 = normalize(vec3(-0.78, 0.42, 0.46)), c2 = normalize(vec3(0.78, 0.38, -0.48));
        float w1 = 0.26 + 1.3 * r, w2 = 0.26 + 1.3 * r;
        env += vec3(0.55, 2.85, 3.80) * exp(-max(0.0, 2.0*(1.0-dot(d,c1)))/(w1*w1)) * pow(0.26/w1, 1.3);
        env += vec3(3.60, 0.65, 2.40) * exp(-max(0.0, 2.0*(1.0-dot(d,c2)))/(w2*w2)) * pow(0.26/w2, 1.3);
        return env;
      }}
      float hz = 1.0 / (1.0 + exp(d.y * 7.5));
      vec3 env = mix(vec3(0.052, 0.056, 0.068), vec3(0.26, 0.265, 0.28), hz);
      float band = exp(-pow((d.y + 0.03) / (0.08 + 0.45 * r), 2.0)) * (1.0 - 0.55 * r);
      env += vec3(0.34, 0.35, 0.38) * band;
      vec3 b1 = normalize(vec3(0.24, 0.93, 0.28));
      vec3 b2 = normalize(vec3(-0.70, 0.47, 0.54));
      vec3 b3 = normalize(vec3(0.76, 0.46, -0.46));
      float w1 = 0.30 + 1.35 * r, w2 = 0.22 + 1.35 * r, w3 = 0.20 + 1.35 * r;
      env += vec3(3.40, 3.30, 3.12) * exp(-max(0.0, 2.0*(1.0-dot(d,b1))) / (w1*w1)) * pow(0.30/w1, 1.35);
      env += vec3(2.15, 2.08, 1.98) * exp(-max(0.0, 2.0*(1.0-dot(d,b2))) / (w2*w2)) * pow(0.22/w2, 1.35);
      env += vec3(1.75, 1.96, 2.35) * exp(-max(0.0, 2.0*(1.0-dot(d,b3))) / (w3*w3)) * pow(0.20/w3, 1.35);
      return env;
    }}
    void main() {{
      if (uChan == 99) {{
        // Ombre de contact douce radiale projetée au sol !
        float d = length(vUV * 2.0 - 1.0);
        float a = 0.46 * pow(clamp(1.0 - d, 0.0, 1.0), 2.1);
        gl_FragColor = vec4(0.02, 0.02, 0.03, a);
        return;
      }}
      if (uWire) {{ gl_FragColor = vec4(0.88, 0.78, 0.48, 1.0); return; }}
      vec3 N = normalize(vNrm);
      if (!gl_FrontFacing) N = -N;
      vec3 albSrgb = uBaseCol.rgb;
      if (uHasAlb) albSrgb *= texture2D(uAlbTex, vUV).rgb;
      vec3 albedo = pow(clamp(albSrgb, 0.0, 1.0), vec3(2.2));
      float ao = 1.0, rough = uRough, metal = uMetal;
      if (uHasMR) {{
        vec4 mr = texture2D(uMRTex, vUV);
        ao = clamp(mr.r, 0.12, 1.0);
        rough = clamp(mr.g * rough, 0.045, 1.0);
        metal = clamp(mr.b * metal, 0.0, 1.0);
      }}
      rough = clamp(rough, 0.045, 1.0);
      if (uHasNrm) {{
        vec3 mapN = texture2D(uNrmTex, vUV).xyz * 2.0 - 1.0;
        vec3 dp1 = dFdx(vViewPos), dp2 = dFdy(vViewPos);
        vec2 duv1 = dFdx(vUV), duv2 = dFdy(vUV);
        vec3 dp2perp = cross(dp2, N), dp1perp = cross(N, dp1);
        vec3 T = dp2perp * duv1.x + dp1perp * duv2.x;
        vec3 B = dp2perp * duv1.y + dp1perp * duv2.y;
        float invmax = inversesqrt(max(dot(T,T), dot(B,B)) + 1e-8);
        N = normalize(mat3(T * invmax, B * invmax, N) * mapN);
      }}
      // Modes d'inspection technique Sketchfab-style
      if (uChan == 1) {{ gl_FragColor = vec4(albSrgb, 1.0); return; }}
      if (uChan == 2) {{ gl_FragColor = vec4(vec3(rough), 1.0); return; }}
      if (uChan == 3) {{ gl_FragColor = vec4(vec3(metal), 1.0); return; }}
      if (uChan == 4) {{ gl_FragColor = vec4(N * 0.5 + 0.5, 1.0); return; }}
      if (uChan == 5) {{ gl_FragColor = vec4(vec3(ao), 1.0); return; }}
      vec3 V = normalize(-vViewPos);
      float ndv = max(dot(N, V), 0.001);
      float alpha = rough * rough, alpha2 = alpha * alpha;
      float kg = pow(rough + 1.0, 2.0) * 0.125;
      float g1v = ndv / (ndv * (1.0 - kg) + kg);
      vec3 F0 = mix(vec3(0.04), albedo, metal);

      vec3 Ldirs[3]; vec3 Lcols[3];
      Ldirs[0] = normalize(vec3(0.48, 0.62, 0.62)); Lcols[0] = vec3(2.65, 2.58, 2.46);
      Ldirs[1] = normalize(vec3(-0.70, 0.25, 0.67)); Lcols[1] = vec3(0.92, 0.98, 1.12);
      Ldirs[2] = normalize(vec3(0.08, 0.35, -0.93)); Lcols[2] = vec3(1.35, 1.44, 1.62);
      vec3 lo = vec3(0.0);
      for (int i = 0; i < 3; i++) {{
        vec3 L = Ldirs[i];
        float ndl = max(dot(N, L), 0.0);
        vec3 H = normalize(L + V);
        float ndh = max(dot(N, H), 0.0);
        float vdh = max(dot(V, H), 0.0);
        float dd = ndh * ndh * (alpha2 - 1.0) + 1.0;
        float D = alpha2 / (3.14159265 * dd * dd + 1e-7);
        float G = g1v * (ndl / (ndl * (1.0 - kg) + kg + 1e-7));
        vec3 F = F0 + (1.0 - F0) * pow(1.0 - vdh, 5.0);
        vec3 spec = (D * G * F) / max(4.0 * ndv * ndl, 1e-4);
        lo += ((1.0 - F) * (1.0 - metal) * albedo / 3.14159265 + spec) * Lcols[i] * ndl;
      }}
      vec3 R = reflect(-V, N);
      vec3 envSpec = studioHDRI(R, rough);
      vec3 envDiff = studioHDRI(N, 0.92);
      vec3 Fenv = F0 + (max(vec3(1.0 - rough), F0) - F0) * pow(1.0 - ndv, 5.0);
      float specAO = clamp(pow(ndv + ao, alpha) - 1.0 + ao, 0.0, 1.0);
      vec3 ibl = albedo * (1.0 - metal) * envDiff * 0.42 * ao
               + envSpec * Fenv * (1.0 - 0.32 * rough) * specAO;
      vec3 col = lo * (0.35 + 0.65 * ao) + ibl + pow(clamp(uEmissive, 0.0, 1.0), vec3(2.2));
      gl_FragColor = vec4(aces(col * 1.06), uBaseCol.a);
    }}`;

  function compile(type, src) {{
    const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
      throw new Error(gl.getShaderInfoLog(s));
    return s;
  }}
  const prog = gl.createProgram();
  gl.attachShader(prog, compile(gl.VERTEX_SHADER, vsSrc));
  gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, fsSrc));
  gl.linkProgram(prog);
  gl.useProgram(prog);

  const loc = {{
    aPos: gl.getAttribLocation(prog, "aPos"),
    aNrm: gl.getAttribLocation(prog, "aNrm"),
    aUV:  gl.getAttribLocation(prog, "aUV"),
    uMVP: gl.getUniformLocation(prog, "uMVP"),
    uModel: gl.getUniformLocation(prog, "uModel"),
    uView: gl.getUniformLocation(prog, "uView"),
    uBaseCol: gl.getUniformLocation(prog, "uBaseCol"),
    uEmissive: gl.getUniformLocation(prog, "uEmissive"),
    uMetal: gl.getUniformLocation(prog, "uMetal"),
    uRough: gl.getUniformLocation(prog, "uRough"),
    uEnv: gl.getUniformLocation(prog, "uEnv"),
    uChan: gl.getUniformLocation(prog, "uChan"),
    uHasAlb: gl.getUniformLocation(prog, "uHasAlb"),
    uHasMR: gl.getUniformLocation(prog, "uHasMR"),
    uHasNrm: gl.getUniformLocation(prog, "uHasNrm"),
    uWire: gl.getUniformLocation(prog, "uWire"),
    uAlbTex: gl.getUniformLocation(prog, "uAlbTex"),
    uMRTex: gl.getUniformLocation(prog, "uMRTex"),
    uNrmTex: gl.getUniformLocation(prog, "uNrmTex"),
  }};

  // --- Décodeur GLB binaire (glTF 2.0 complet) ---
  const dv = new DataView(bytes.buffer);
  if (dv.getUint32(0, true) !== 0x46546C67) {{ showErr("GLB invalide"); return; }}
  let offset = 12, gltf = null, binChunk = null;
  while (offset < bytes.length) {{
    const clen = dv.getUint32(offset, true);
    const ctype = dv.getUint32(offset + 4, true);
    if (ctype === 0x4E4F534A)
      gltf = JSON.parse(new TextDecoder().decode(bytes.subarray(offset + 8, offset + 8 + clen)));
    else if (ctype === 0x004E4942)
      binChunk = bytes.subarray(offset + 8, offset + 8 + clen);
    offset += 8 + clen;
  }}

  const COMP_SIZES = {{ 5120:1, 5121:1, 5122:2, 5123:2, 5125:4, 5126:4 }};
  const TYPE_COUNTS = {{ SCALAR:1, VEC2:2, VEC3:3, VEC4:4, MAT4:16 }};
  function readAcc(idx) {{
    if (idx === undefined || idx === null) return null;
    const acc = gltf.accessors[idx];
    const bv = gltf.bufferViews[acc.bufferView];
    const nComp = TYPE_COUNTS[acc.type];
    const cSize = COMP_SIZES[acc.componentType];
    const stride = bv.byteStride || (nComp * cSize);
    const base = (bv.byteOffset || 0) + (acc.byteOffset || 0);
    const out = new Float32Array(acc.count * nComp);
    const v = new DataView(binChunk.buffer, binChunk.byteOffset + base, acc.count * stride);
    for (let i = 0; i < acc.count; i++) {{
      for (let k = 0; k < nComp; k++) {{
        const o = i * stride + k * cSize;
        if (acc.componentType === 5126) out[i*nComp+k] = v.getFloat32(o, true);
        else if (acc.componentType === 5125) out[i*nComp+k] = v.getUint32(o, true);
        else if (acc.componentType === 5123) out[i*nComp+k] = v.getUint16(o, true);
        else if (acc.componentType === 5121) out[i*nComp+k] = v.getUint8(o);
      }}
    }}
    return out;
  }}

  const glTextures = [];
  function loadTex(texIdx) {{
    if (texIdx === undefined || texIdx === null) return null;
    if (glTextures[texIdx]) return glTextures[texIdx];
    const imgDef = gltf.images[gltf.textures[texIdx].source];
    const bv = gltf.bufferViews[imgDef.bufferView];
    const slice = binChunk.subarray(bv.byteOffset || 0, (bv.byteOffset || 0) + bv.byteLength);
    const blob = new Blob([slice], {{ type: imgDef.mimeType || "image/png" }});
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([200,200,200,255]));
    const im = new Image();
    im.onload = () => {{
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, im);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    }};
    im.src = URL.createObjectURL(blob);
    glTextures[texIdx] = tex;
    return tex;
  }}

  const drawCalls = [];
  const bbox = {{ min:[Infinity,Infinity,Infinity], max:[-Infinity,-Infinity,-Infinity] }};

  function visitNode(ni, parentM) {{
    const node = gltf.nodes[ni];
    const localM = node.matrix ? new Float32Array(node.matrix)
                 : m4TRS(node.translation || [0,0,0], node.rotation || [0,0,0,1], node.scale || [1,1,1]);
    const worldM = m4Mul(parentM, localM);
    if (node.mesh !== undefined) {{
      for (const prim of gltf.meshes[node.mesh].primitives) {{
        const pos = readAcc(prim.attributes.POSITION);
        const nrm = readAcc(prim.attributes.NORMAL);
        const uv  = readAcc(prim.attributes.TEXCOORD_0);
        const idx = readAcc(prim.indices);
        const triVerts = idx ? idx.length : (pos.length / 3);
        const pExp = new Float32Array(triVerts * 3);
        const nExp = new Float32Array(triVerts * 3);
        const uExp = new Float32Array(triVerts * 2);
        for (let i = 0; i < triVerts; i++) {{
          const vi = idx ? idx[i] : i;
          const x = pos[vi*3], y = pos[vi*3+1], z = pos[vi*3+2];
          pExp[i*3]=x; pExp[i*3+1]=y; pExp[i*3+2]=z;
          const wx = worldM[0]*x + worldM[4]*y + worldM[8]*z + worldM[12];
          const wy = worldM[1]*x + worldM[5]*y + worldM[9]*z + worldM[13];
          const wz = worldM[2]*x + worldM[6]*y + worldM[10]*z + worldM[14];
          if (wx < bbox.min[0]) bbox.min[0] = wx; if (wx > bbox.max[0]) bbox.max[0] = wx;
          if (wy < bbox.min[1]) bbox.min[1] = wy; if (wy > bbox.max[1]) bbox.max[1] = wy;
          if (wz < bbox.min[2]) bbox.min[2] = wz; if (wz > bbox.max[2]) bbox.max[2] = wz;
          if (nrm) {{ nExp[i*3]=nrm[vi*3]; nExp[i*3+1]=nrm[vi*3+1]; nExp[i*3+2]=nrm[vi*3+2]; }}
          if (uv)  {{ uExp[i*2]=uv[vi*2];  uExp[i*2+1]=uv[vi*2+1]; }}
        }}
        if (!nrm) {{
          for (let i = 0; i < triVerts; i += 3) {{
            const ax=pExp[i*3+3]-pExp[i*3], ay=pExp[i*3+4]-pExp[i*3+1], az=pExp[i*3+5]-pExp[i*3+2];
            const bx=pExp[i*3+6]-pExp[i*3], by=pExp[i*3+7]-pExp[i*3+1], bz=pExp[i*3+8]-pExp[i*3+2];
            let nx=ay*bz-az*by, ny=az*bx-ax*bz, nz=ax*by-ay*bx;
            const l = Math.hypot(nx,ny,nz)||1; nx/=l; ny/=l; nz/=l;
            for (let k=0;k<3;k++) {{ nExp[(i+k)*3]=nx; nExp[(i+k)*3+1]=ny; nExp[(i+k)*3+2]=nz; }}
          }}
        }}
        const mkBuf = (arr) => {{ const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, arr, gl.STATIC_DRAW); return b; }};
        const matDef = (prim.material !== undefined && gltf.materials) ? gltf.materials[prim.material] : {{}};
        const pbrDef = matDef.pbrMetallicRoughness || {{}};
        const bc = pbrDef.baseColorFactor || [0.8, 0.8, 0.8, 1.0];
        drawCalls.push({{
          bPos: mkBuf(pExp), bNrm: mkBuf(nExp), bUV: mkBuf(uExp), count: triVerts,
          model: worldM,
          baseCol: bc,
          emissive: matDef.emissiveFactor || [0,0,0],
          metal: pbrDef.metallicFactor !== undefined ? pbrDef.metallicFactor : 0.0,
          rough: pbrDef.roughnessFactor !== undefined ? pbrDef.roughnessFactor : 0.5,
          albTex: pbrDef.baseColorTexture ? loadTex(pbrDef.baseColorTexture.index) : null,
          mrTex:  pbrDef.metallicRoughnessTexture ? loadTex(pbrDef.metallicRoughnessTexture.index) : null,
          nrmTex: matDef.normalTexture ? loadTex(matDef.normalTexture.index) : null,
          transparent: (bc[3] < 0.999) || matDef.alphaMode === "BLEND",
        }});
      }}
    }}
    if (node.children) for (const c of node.children) visitNode(c, worldM);
  }}
  const sceneDef = gltf.scenes[gltf.scene || 0];
  for (const n of sceneDef.nodes) visitNode(n, m4Identity());
  drawCalls.sort((a, b) => Number(a.transparent) - Number(b.transparent));

  // Disque d'ombre de contact douce au sol + grille circulaire discrète
  const center = [(bbox.min[0]+bbox.max[0])/2, (bbox.min[1]+bbox.max[1])/2, (bbox.min[2]+bbox.max[2])/2];
  const radius = Math.hypot(bbox.max[0]-bbox.min[0], bbox.max[1]-bbox.min[1], bbox.max[2]-bbox.min[2]) / 2 || 0.5;
  const gLines = [];
  const gs = radius * 1.15, gy = bbox.min[1] - radius * 0.004;
  for (let i = -5; i <= 5; i++) {{
    const t = (i / 5) * gs;
    gLines.push(center[0]-gs, gy, center[2]+t, center[0]+gs, gy, center[2]+t);
    gLines.push(center[0]+t, gy, center[2]-gs, center[0]+t, gy, center[2]+gs);
  }}
  const gridBuf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, gridBuf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(gLines), gl.STATIC_DRAW);
  const gridZero = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, gridZero);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(gLines.length), gl.STATIC_DRAW);

  const sx = Math.max((bbox.max[0]-bbox.min[0])*0.68, radius*0.35);
  const sz = Math.max((bbox.max[2]-bbox.min[2])*0.68, radius*0.35);
  const sy = bbox.min[1] - radius * 0.002;
  const shPos = new Float32Array([
    center[0]-sx, sy, center[2]-sz,  center[0]+sx, sy, center[2]-sz,  center[0]+sx, sy, center[2]+sz,
    center[0]-sx, sy, center[2]-sz,  center[0]+sx, sy, center[2]+sz,  center[0]-sx, sy, center[2]+sz
  ]);
  const shUV = new Float32Array([0,0, 1,0, 1,1,  0,0, 1,1, 0,1]);
  const shNrm = new Float32Array([0,1,0, 0,1,0, 0,1,0,  0,1,0, 0,1,0, 0,1,0]);
  const bShPos = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, bShPos); gl.bufferData(gl.ARRAY_BUFFER, shPos, gl.STATIC_DRAW);
  const bShUV  = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, shUV,  gl.STATIC_DRAW);
  const bShNrm = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, bShNrm); gl.bufferData(gl.ARRAY_BUFFER, shNrm, gl.STATIC_DRAW);

  const jointNodes = (gltf.nodes || []).filter(n => n.extras && n.extras.joint);
  if (jointNodes.length > 0) document.getElementById("animBtn").style.display = "inline-block";

  // Contrôles caméra + inspecteur matériaux/HDRI
  let az = 0.73, el = 0.38, dist = radius * 2.95;
  let target = [...center], autoRot = true, wire = false, envMode = 0, chanMode = 0, animJoints = false, animT = 0, drag = null;
  canvas.addEventListener("pointerdown", e => {{
    canvas.setPointerCapture(e.pointerId);
    drag = {{ x:e.clientX, y:e.clientY, pan: e.button === 2 || e.shiftKey }};
  }});
  canvas.addEventListener("pointermove", e => {{
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag.x = e.clientX; drag.y = e.clientY;
    if (drag.pan) {{
      const s = dist * 0.0014;
      target[0] -= Math.cos(az) * dx * s;
      target[2] += Math.sin(az) * dx * s;
      target[1] += dy * s;
    }} else {{
      autoRot = false;
      document.getElementById("rot").textContent = "▶ rotation";
      az -= dx * 0.007;
      el = Math.max(-1.45, Math.min(1.45, el + dy * 0.007));
    }}
  }});
  canvas.addEventListener("pointerup", () => drag = null);
  canvas.addEventListener("contextmenu", e => e.preventDefault());
  canvas.addEventListener("wheel", e => {{
    e.preventDefault();
    dist = Math.max(radius * 0.4, Math.min(radius * 12, dist * Math.exp(e.deltaY * 0.001)));
  }}, {{ passive: false }});

  document.getElementById("rot").onclick = e => {{
    autoRot = !autoRot;
    e.target.textContent = autoRot ? "⏸ rotation" : "▶ rotation";
  }};
  const setView = (a, e) => {{ az = a; el = e; target = [...center]; autoRot = false; document.getElementById("rot").textContent = "▶ rotation"; }};
  document.getElementById("v34").onclick    = () => setView(0.73, 0.38);
  document.getElementById("vfront").onclick = () => setView(0.0, 0.14);
  document.getElementById("vside").onclick  = () => setView(Math.PI/2, 0.14);
  document.getElementById("vtop").onclick   = () => setView(0.0, 1.35);
  document.getElementById("envSel").onchange = e => {{ envMode = parseInt(e.target.value, 10) || 0; }};
  document.getElementById("chanSel").onchange = e => {{
    const v = parseInt(e.target.value, 10) || 0;
    wire = (v === 6);
    chanMode = wire ? 0 : v;
  }};
  document.getElementById("animBtn").onclick = e => {{
    animJoints = !animJoints;
    e.target.textContent = animJoints ? "⏸ stopper articulations" : "⚙ animer articulations";
  }};

  let last = performance.now();
  function frame(now) {{
    const dt = (now - last) / 1000; last = now;
    if (autoRot) az += dt * 0.35;
    if (animJoints) animT += dt;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(2, Math.floor(canvas.clientWidth * dpr));
    const h = Math.max(2, Math.floor(canvas.clientHeight * dpr));
    if (canvas.width !== w || canvas.height !== h) {{ canvas.width = w; canvas.height = h; }}
    gl.viewport(0, 0, w, h);
    gl.clearColor(0, 0, 0, 0);
    gl.enable(gl.DEPTH_TEST);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    const eye = [
      target[0] + dist * Math.sin(az) * Math.cos(el),
      target[1] + dist * Math.sin(el),
      target[2] + dist * Math.cos(az) * Math.cos(el),
    ];
    const V = m4LookAt(eye, target, [0,1,0]);
    const P = m4Persp(0.66, w / h, radius * 0.04, radius * 40);
    const PV = m4Mul(P, V);

    gl.uniform1i(loc.uEnv, envMode);

    // Ombre de contact douce sous le modèle
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false);
    gl.bindBuffer(gl.ARRAY_BUFFER, bShPos); gl.enableVertexAttribArray(loc.aPos); gl.vertexAttribPointer(loc.aPos, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, bShNrm); gl.enableVertexAttribArray(loc.aNrm); gl.vertexAttribPointer(loc.aNrm, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, bShUV);  gl.enableVertexAttribArray(loc.aUV);  gl.vertexAttribPointer(loc.aUV,  2, gl.FLOAT, false, 0, 0);
    gl.uniformMatrix4fv(loc.uModel, false, m4Identity());
    gl.uniformMatrix4fv(loc.uView, false, V);
    gl.uniformMatrix4fv(loc.uMVP, false, PV);
    gl.uniform1i(loc.uChan, 99);
    gl.uniform1i(loc.uWire, 0);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    gl.disable(gl.BLEND); gl.depthMask(true);

    // Grille au sol
    gl.bindBuffer(gl.ARRAY_BUFFER, gridBuf);
    gl.enableVertexAttribArray(loc.aPos); gl.vertexAttribPointer(loc.aPos, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, gridZero);
    gl.enableVertexAttribArray(loc.aNrm); gl.vertexAttribPointer(loc.aNrm, 3, gl.FLOAT, false, 0, 0);
    gl.enableVertexAttribArray(loc.aUV);  gl.vertexAttribPointer(loc.aUV,  2, gl.FLOAT, false, 0, 0);
    gl.uniformMatrix4fv(loc.uModel, false, m4Identity());
    gl.uniformMatrix4fv(loc.uView, false, V);
    gl.uniformMatrix4fv(loc.uMVP, false, PV);
    gl.uniform1i(loc.uChan, 0);
    gl.uniform1i(loc.uWire, 1);
    gl.uniform4f(loc.uBaseCol, 0.25, 0.25, 0.3, 0.35);
    gl.drawArrays(gl.LINES, 0, gLines.length / 3);

    gl.uniform1i(loc.uChan, chanMode);
    for (const dc of drawCalls) {{
      if (dc.transparent) {{ gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false); }}
      else {{ gl.disable(gl.BLEND); gl.depthMask(true); }}

      gl.bindBuffer(gl.ARRAY_BUFFER, dc.bPos);
      gl.vertexAttribPointer(loc.aPos, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, dc.bNrm);
      gl.vertexAttribPointer(loc.aNrm, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, dc.bUV);
      gl.vertexAttribPointer(loc.aUV,  2, gl.FLOAT, false, 0, 0);

      gl.uniformMatrix4fv(loc.uModel, false, dc.model);
      gl.uniformMatrix4fv(loc.uView, false, V);
      gl.uniformMatrix4fv(loc.uMVP, false, m4Mul(PV, dc.model));
      gl.uniform4fv(loc.uBaseCol, dc.baseCol);
      gl.uniform3fv(loc.uEmissive, dc.emissive);
      gl.uniform1f(loc.uMetal, dc.metal);
      gl.uniform1f(loc.uRough, dc.rough);
      gl.uniform1i(loc.uWire, wire ? 1 : 0);

      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, dc.albTex);
      gl.uniform1i(loc.uAlbTex, 0); gl.uniform1i(loc.uHasAlb, dc.albTex ? 1 : 0);
      gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, dc.mrTex);
      gl.uniform1i(loc.uMRTex, 1);  gl.uniform1i(loc.uHasMR, dc.mrTex ? 1 : 0);
      gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, dc.nrmTex);
      gl.uniform1i(loc.uNrmTex, 2); gl.uniform1i(loc.uHasNrm, dc.nrmTex ? 1 : 0);

      gl.drawArrays(wire ? gl.LINES : gl.TRIANGLES, 0, dc.count);
    }}
    gl.depthMask(true);
    gl.disable(gl.BLEND);
    requestAnimationFrame(frame);
  }}
  requestAnimationFrame(frame);
}})();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Preview HTML 100% hors-ligne (WebGL PBR)")
    ap.add_argument("--dir", required=True, help="dossier de sortie de la génération")
    ap.add_argument("--title", default=None)
    ap.add_argument("--glb", default=None, help="GLB spécifique (défaut : 1er trouvé)")
    args = ap.parse_args()
    p = build_preview(args.dir, title=args.title, glb=args.glb)
    if p:
        print(f"preview → {p}")


if __name__ == "__main__":
    main()
