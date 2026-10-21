"""
usdz_export — export USDZ natif via usd-core (Pixar) + fallback USDA zippé.

Supporte à la fois les matériaux PBR unis ET les atlas de textures UV embarqués
(`UsdUVTexture` + `primvars:st` : albedo, metallicRoughness, normalMap) dans un
package USDZ aligné 64 octets 100 % autonome (Apple AR Quick Look / RealityKit).
"""
from __future__ import annotations

import io
import os
import re
import shutil
import struct
import tempfile
import zipfile
import numpy as np


def _safe(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not name or name[0].isdigit():
        name = "n_" + name
    return name


def _pack_usdz_aligned(entries: list[tuple[str, bytes]], usdz_path: str) -> str:
    """Construit une archive `.usdz` conforme Apple/Pixar (ZIP non compressé,
    chaque payload aligné sur 64 octets, `.usdc` en première entrée)."""
    buf = bytearray()
    central = []
    for arcname, payload in entries:
        name_b = arcname.encode("utf-8")
        crc = zipfile.crc32(payload) & 0xFFFFFFFF
        local_off = len(buf)
        data_start_no_extra = local_off + 30 + len(name_b)
        rem = data_start_no_extra % 64
        extra_len = (64 - rem) % 64
        if 0 < extra_len < 4:
            extra_len += 64
        extra = (b"\x86\x19" + struct.pack("<H", extra_len - 4) + b"\x00" * (extra_len - 4)) if extra_len else b""
        lfh = struct.pack(
            "<4sHHHHHIIIHH",
            b"PK\x03\x04", 20, 0, 0, 0, 0,
            crc, len(payload), len(payload),
            len(name_b), len(extra),
        )
        buf.extend(lfh)
        buf.extend(name_b)
        buf.extend(extra)
        buf.extend(payload)
        central.append((name_b, extra, crc, len(payload), local_off))

    cd_off = len(buf)
    for name_b, extra, crc, sz, local_off in central:
        cdfh = struct.pack(
            "<4sHHHHHHIIIHHHHHII",
            b"PK\x01\x02", 20, 20, 0, 0, 0, 0,
            crc, sz, sz,
            len(name_b), len(extra), 0, 0, 0, 0, local_off,
        )
        buf.extend(cdfh)
        buf.extend(name_b)
        buf.extend(extra)
    cd_size = len(buf) - cd_off
    eocd = struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06", 0, 0, len(central), len(central), cd_size, cd_off, 0,
    )
    buf.extend(eocd)
    with open(usdz_path, "wb") as fh:
        fh.write(buf)
    return usdz_path


def _export_with_pxr(scene, usdz_path: str) -> str:
    from pxr import Usd, UsdGeom, UsdShade, UsdUtils, Sdf, Vt, Gf

    tmp_dir = tempfile.mkdtemp(prefix="usdz_forge_")
    try:
        tmp_usd = os.path.join(tmp_dir, "scene.usdc")
        stage = Usd.Stage.CreateNew(tmp_usd)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)

        UsdGeom.Xform.Define(stage, "/Root")

        mat_index = 0
        for gname, geom in scene.geometry.items():
            prim_name = _safe(gname)
            mesh = UsdGeom.Mesh.Define(stage, f"/Root/{prim_name}")
            verts = np.asarray(geom.vertices, dtype=np.float32)
            faces = np.asarray(geom.faces, dtype=np.int32)
            counts = np.full(len(faces), 3, dtype=np.int32)
            normals = np.asarray(geom.vertex_normals, dtype=np.float32)

            mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(verts))
            mesh.CreateFaceVertexCountsAttr(Vt.IntArray.FromNumpy(counts))
            mesh.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(faces.flatten()))
            mesh.CreateNormalsAttr(Vt.Vec3fArray.FromNumpy(normals))
            mesh.SetNormalsInterpolation(UsdGeom.Tokens.vertex)

            uv = getattr(geom.visual, "uv", None)
            has_uv = uv is not None and len(uv) == len(geom.vertices)
            if has_uv:
                pv_api = UsdGeom.PrimvarsAPI(mesh)
                st = pv_api.CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray,
                                          UsdGeom.Tokens.vertex)
                st.Set(Vt.Vec2fArray.FromNumpy(np.asarray(uv, dtype=np.float32)))

            material = getattr(geom.visual, "material", None)
            col = np.array(getattr(material, "baseColorFactor", [0.75, 0.75, 0.75, 1.0]),
                           dtype=float)
            if col.max() > 1.001:
                col = col / 255.0
            metallic = float(getattr(material, "metallicFactor", None)
                             if getattr(material, "metallicFactor", None) is not None else 0.0)
            roughness = float(getattr(material, "roughnessFactor", None)
                              if getattr(material, "roughnessFactor", None) is not None else 0.5)
            opacity = float(col[3]) if len(col) > 3 else 1.0
            emis = getattr(material, "emissiveFactor", None)

            mname = _safe(getattr(material, "name", None) or f"m{mat_index}")
            mat_path = f"/Root/Mtls/{mname}_{mat_index}"
            material_prim = UsdShade.Material.Define(stage, mat_path)
            shader = UsdShade.Shader.Define(stage, mat_path + "/Surface")
            shader.CreateIdAttr("UsdPreviewSurface")

            tex_img = (getattr(material, "baseColorTexture", None)
                       or getattr(geom.visual, "image", None))
            if has_uv and tex_img is not None:
                st_reader = UsdShade.Shader.Define(stage, mat_path + "/PrimvarReader")
                st_reader.CreateIdAttr("UsdPrimvarReader_float2")
                st_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
                st_out = st_reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)

                alb_rel = f"textures/tex_{mat_index}_albedo.png"
                os.makedirs(os.path.join(tmp_dir, "textures"), exist_ok=True)
                tex_img.save(os.path.join(tmp_dir, alb_rel))
                alb_sh = UsdShade.Shader.Define(stage, mat_path + "/DiffuseTex")
                alb_sh.CreateIdAttr("UsdUVTexture")
                alb_sh.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(f"./{alb_rel}"))
                alb_sh.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(st_out)
                alb_rgb = alb_sh.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
                shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(alb_rgb)

                mr_img = getattr(material, "metallicRoughnessTexture", None)
                if mr_img is not None:
                    mr_rel = f"textures/tex_{mat_index}_mr.png"
                    mr_img.save(os.path.join(tmp_dir, mr_rel))
                    mr_sh = UsdShade.Shader.Define(stage, mat_path + "/MRTex")
                    mr_sh.CreateIdAttr("UsdUVTexture")
                    mr_sh.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(f"./{mr_rel}"))
                    mr_sh.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(st_out)
                    g_out = mr_sh.CreateOutput("g", Sdf.ValueTypeNames.Float)
                    b_out = mr_sh.CreateOutput("b", Sdf.ValueTypeNames.Float)
                    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).ConnectToSource(g_out)
                    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).ConnectToSource(b_out)
                else:
                    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
                    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
            else:
                shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
                    Gf.Vec3f(float(col[0]), float(col[1]), float(col[2])))
                shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
                shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)

            if opacity < 0.999:
                shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(opacity)
            if emis is not None:
                shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(
                    Gf.Vec3f(float(emis[0]), float(emis[1]), float(emis[2])))
            material_prim.CreateSurfaceOutput().ConnectToSource(
                shader.ConnectableAPI(), "surface")
            UsdShade.MaterialBindingAPI(mesh.GetPrim()).Bind(material_prim)
            mat_index += 1

        stage.Save()
        with open(tmp_usd, "rb") as fh:
            entries = [("scene.usdc", fh.read())]
        tex_root = os.path.join(tmp_dir, "textures")
        if os.path.isdir(tex_root):
            for fn in sorted(os.listdir(tex_root)):
                with open(os.path.join(tex_root, fn), "rb") as fh:
                    entries.append((f"textures/{fn}", fh.read()))
        return _pack_usdz_aligned(entries, os.path.abspath(usdz_path))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _export_fallback_usda(scene, usdz_path: str) -> str:
    """Fallback : USDA texte zippé (stored, aligné 64 B)."""
    lines = [
        '#usda 1.0',
        '(',
        '    upAxis = "Z"',
        '    metersPerUnit = 1',
        ')',
        '',
        'def Xform "Root"',
        '{',
    ]
    for gname, geom in scene.geometry.items():
        pname = _safe(gname)
        verts = np.asarray(geom.vertices, dtype=np.float32)
        faces = np.asarray(geom.faces, dtype=np.int32)
        n = geom.vertex_normals.astype(np.float32)
        material = getattr(geom.visual, "material", None)
        col = np.array(getattr(material, "baseColorFactor", [0.75, 0.75, 0.75, 1.0]), dtype=float)
        if col.max() > 1.001:
            col = col / 255.0
        lines += [
            f'    def Mesh "{pname}"',
            '    {',
            f'        int[] faceVertexCounts = {list(np.full(len(faces), 3))}'.replace(",", ""),
            f'        int[] faceVertexIndices = {list(faces.flatten())}'.replace(",", ""),
            f'        point3f[] points = [{", ".join(f"({v[0]:.5f}, {v[1]:.5f}, {v[2]:.5f})" for v in verts)}]',
            f'        normal3f[] normals = [{", ".join(f"({v[0]:.4f}, {v[1]:.4f}, {v[2]:.4f})" for v in n)}]',
            '        interpolation = "vertex"',
            f'        color3f[] primvars:displayColor = [{f"({col[0]:.4f}, {col[1]:.4f}, {col[2]:.4f})"}]',
            '    }',
        ]
    lines.append('}')

    data = ("\n".join(lines) + "\n").encode("utf-8")
    bio = io.BytesIO()
    header = zipfile.ZipInfo(os.path.basename(usdz_path).replace(".usdz", ".usda"))
    header.compress_type = zipfile.ZIP_STORED
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_STORED) as z:
        z.writestr(header, data)
    raw = bio.getvalue()
    pad = (64 - (len(raw) % 64)) % 64
    with open(usdz_path, "wb") as out:
        out.write(raw)
        if pad:
            out.write(b"\x00" * pad)
    return usdz_path


def export_usdz(scene, usdz_path: str) -> dict:
    """Exporte la scène en .usdz. Retourne {'path': ..., 'engine': 'usd-core'|'usda-fallback'}."""
    os.makedirs(os.path.dirname(os.path.abspath(usdz_path)) or ".", exist_ok=True)
    try:
        _export_with_pxr(scene, usdz_path)
        return {"path": usdz_path, "engine": "usd-core"}
    except ImportError:
        _export_fallback_usda(scene, usdz_path)
        return {"path": usdz_path, "engine": "usda-fallback"}
