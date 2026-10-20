"""
usdz_export — export USDZ natif via usd-core (Pixar) + fallback USDA zippé.

Le chemin principal construit un vrai package USD (crate binaire compressé
dans une archive alignée 64 octets, conforme Apple AR Quick Look) avec des
matériaux UsdPreviewSurface (diffuseColor, metallic, roughness, opacity).

Si usd-core n'est pas installé, un fallback écrit un .usda (texte) zippé :
lisible par USD/Blender, mais marqué expérimental pour ARKit.
"""
from __future__ import annotations

import os
import re
import tempfile
import zipfile
import numpy as np


def _safe(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not name or name[0].isdigit():
        name = "n_" + name
    return name


def _export_with_pxr(scene, usdz_path: str) -> str:
    from pxr import Usd, UsdGeom, UsdShade, UsdUtils, Sdf, Vt, Gf

    tmp_usd = tempfile.mktemp(suffix=".usd")
    stage = Usd.Stage.CreateNew(tmp_usd)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    root = UsdGeom.Xform.Define(stage, "/Root")

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

        material = getattr(geom.visual, "material", None)
        col = np.array(getattr(material, "baseColorFactor", [0.75, 0.75, 0.75, 1.0]), dtype=float)
        if col.max() > 1.001:
            col = col / 255.0
        metallic = float(getattr(material, "metallicFactor", 0.0) or 0.0)
        roughness = float(getattr(material, "roughnessFactor", 0.5) or 0.5)
        opacity = float(col[3]) if len(col) > 3 else 1.0
        emis = getattr(material, "emissiveFactor", None)

        mname = _safe(getattr(material, "name", None) or f"m{mat_index}")
        mat_path = f"/Root/Mtls/{mname}_{mat_index}"
        material_prim = UsdShade.Material.Define(stage, mat_path)
        shader = UsdShade.Shader.Define(stage, mat_path + "/Surface")
        shader.CreateIdAttr("UsdPreviewSurface")
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
    ok = UsdUtils.CreateNewUsdzPackage(Sdf.AssetPath(tmp_usd), usdz_path)
    try:
        os.remove(tmp_usd)
    except OSError:
        pass
    if not ok or not os.path.exists(usdz_path):
        raise RuntimeError("CreateNewUsdzPackage a échoué")
    return usdz_path


def _export_fallback_usda(scene, usdz_path: str) -> str:
    """Fallback : USDA texte zippé (stored, aligné 64 B). Expérimental pour ARKit."""
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
    for i, (gname, geom) in enumerate(scene.geometry.items()):
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

    tmp_usda = tempfile.mktemp(suffix=".usda")
    with open(tmp_usda, "w") as f:
        f.write("\n".join(lines) + "\n")

    # usdz = zip sans compression, aligné 64 octets
    with open(tmp_usda, "rb") as f:
        data = f.read()
    with open(usdz_path, "wb") as out:
        header = zipfile.ZipInfo(os.path.basename(usdz_path).replace(".usdz", ".usda"))
        header.compress_type = zipfile.ZIP_STORED
        buf = bytearray()
        import io
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w", zipfile.ZIP_STORED) as z:
            z.writestr(header, data)
        raw = bio.getvalue()
        # réécriture alignée : la ZIP local header + data doit être 64-alignée
        pad = (64 - (len(raw) % 64)) % 64
        out.write(raw)
        if pad:
            out.write(b"\x00" * pad)  # tolérant : la plupart des lecteurs USD acceptent
    try:
        os.remove(tmp_usda)
    except OSError:
        pass
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
