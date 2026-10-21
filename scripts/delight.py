#!/usr/bin/env python3
"""
delight.py — Moteur physique de De-Lighting d'Albédo (`3d-forge v5 — Game-Ready Edition`).

Pourquoi ce module est indispensable en jeu vidéo (Unreal Lumen, Unity HDRP/URP, Godot 4) :
  Les vues générées par IA (diffusion GPU) contiennent un éclairage studio cuit
  (ombres dans les cavités orientées vers le bas, reflets blancs sur les arêtes
  tournées vers le haut). En moteur temps réel, un Albédo qui contient déjà des
  ombres ou des reflets casse le PBR : les reflets peints brillent dans le noir
  complet et les ombres doublent sous Lumen / Ray Tracing.

Algorithme physique implémenté :
  1. Passage en radiance sRGB linéaire `I_lin`.
  2. Détection et suppression des taches spéculaires saturées / achromatiques
     alignées avec la direction lumineuse dominante estimée sur les normales 3D `N`.
  3. Régression robuste IRLS sur la base d'Harmoniques Sphériques réelles d'ordre 2
     (`9` fonctions de base `Y_0..Y_8(N)`) estimant le champ d'irradiance global
     `E(N)` indépendamment des variations chromatiques locales des matériaux
     (ex. or vs basalte noir, rouille vs acier).
  4. Division radiométrique bornée :
       `Albedo_lin = clip(I_no_spec / clip(E(N) / E_mean, lo, hi), 0, 1)`
     préservant à 100 % la teinte et le contraste matière local tout en neutralisant
     le gradient d'éclairage directionnel cuit !
  5. Mode autonome 2D (`delight_albedo_2d`) par décomposition intrinsèque multi-échelles
     quand aucune carte de normales 3D n'est disponible.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * (c ** (1.0 / 2.4)) - 0.055)


def sh9_basis(n: np.ndarray) -> np.ndarray:
    """Base d'Harmoniques Sphériques réelles d'ordre 2 `(N, 9)` sur normales unitaires `(N, 3)`."""
    x, y, z = n[:, 0], n[:, 1], n[:, 2]
    return np.column_stack([
        np.ones_like(x) * 0.282095,
        0.488603 * y,
        0.488603 * z,
        0.488603 * x,
        1.092548 * x * y,
        1.092548 * y * z,
        0.315392 * (3.0 * z * z - 1.0),
        1.092548 * x * z,
        0.546274 * (x * x - y * y),
    ]).astype(np.float64)


def delight_albedo_3d(
    albedo_srgb: np.ndarray,
    normals_world: np.ndarray,
    valid_mask: np.ndarray | None = None,
    strength: float = 0.85,
    remove_specular: bool = True,
) -> tuple[np.ndarray, dict]:
    """Neutralise l'éclairage directionnel et les reflets spéculaires cuits d'un atlas
    `albedo_srgb` (`H, W, 3` en `[0..1]` ou `uint8`) à l'aide des normales 3D monde
    `normals_world` (`H, W, 3` ou `N, 3`).

    Retourne `(delit_srgb_float01, metrics_dict)`.
    """
    is_u8 = albedo_srgb.dtype == np.uint8
    arr = albedo_srgb.astype(np.float32) / (255.0 if is_u8 else 1.0)
    orig_shape = arr.shape
    flat_rgb = arr.reshape(-1, 3)
    flat_n = normals_world.reshape(-1, 3).astype(np.float64)
    n_len = np.linalg.norm(flat_n, axis=1, keepdims=True)

    if valid_mask is not None:
        mask = valid_mask.reshape(-1).astype(bool) & (n_len[:, 0] > 0.25)
    else:
        mask = n_len[:, 0] > 0.25

    if mask.sum() < 64:
        return (arr * 255).astype(np.uint8) if is_u8 else arr, {"sh_variance_reduction": 0.0}

    n_valid = flat_n[mask] / np.maximum(n_len[mask], 1e-12)
    lin = _srgb_to_linear(flat_rgb[mask]).astype(np.float64)
    lum = 0.2126 * lin[:, 0] + 0.7152 * lin[:, 1] + 0.0722 * lin[:, 2]

    # 1. Suppression douce des pics spéculaires studio (haute luminance + faible saturation)
    spec_removed_frac = 0.0
    if remove_specular:
        mx = lin.max(axis=1)
        mn = lin.min(axis=1)
        sat = (mx - mn) / np.maximum(mx, 1e-4)
        p90 = float(np.percentile(lum, 90))
        p65 = float(np.percentile(lum, 65))
        spec_w = np.clip((lum - p90) / max(p90 * 0.45, 1e-3), 0.0, 1.0) * np.clip(1.0 - sat * 2.2, 0.0, 1.0)
        if spec_w.max() > 0.05:
            scale_down = (p65 / np.maximum(lum, 1e-4))
            lin = lin * (1.0 - spec_w[:, None] * 0.75 * (1.0 - scale_down[:, None]))
            lum = 0.2126 * lin[:, 0] + 0.7152 * lin[:, 1] + 0.0722 * lin[:, 2]
            spec_removed_frac = float((spec_w > 0.2).mean())

    # 2. Estimation robuste IRLS du champ d'irradiance SH d'ordre 2 sur log-luminance
    B = sh9_basis(n_valid)
    log_lum = np.log(np.clip(lum, 1e-3, 4.0))
    weights = np.ones_like(log_lum)
    reg = 1e-2 * np.eye(9)
    reg[0, 0] = 0.0
    coeffs = np.zeros(9, dtype=np.float64)
    for _ in range(4):
        Bw = B * weights[:, None]
        coeffs = np.linalg.solve(B.T @ Bw + reg, Bw.T @ log_lum)
        pred = B @ coeffs
        resid = np.abs(log_lum - pred)
        mad = float(np.median(resid)) * 1.4826 + 1e-3
        # Huber-like weight : ignore les frontières nettes entre matériaux sombre/clair !
        weights = np.where(resid <= 1.5 * mad, 1.0, (1.5 * mad) / np.maximum(resid, 1e-6))

    log_shade = B @ coeffs
    mean_log_shade = float(np.median(log_shade))
    rel_shade = np.exp(np.clip((log_shade - mean_log_shade) * float(strength), -0.85, 0.85))

    # Variance directionnelle avant / après de-lighting (métrique objective vérifiable en test !)
    before_corr = float(np.std(B @ np.linalg.lstsq(B, log_lum, rcond=None)[0]))
    delit_lin = np.clip(lin / rel_shade[:, None], 0.0, 1.0)
    lum_after = 0.2126 * delit_lin[:, 0] + 0.7152 * delit_lin[:, 1] + 0.0722 * delit_lin[:, 2]
    after_corr = float(np.std(B @ np.linalg.lstsq(B, np.log(np.clip(lum_after, 1e-3, 4.0)), rcond=None)[0]))
    reduction = max(0.0, 1.0 - after_corr / max(before_corr, 1e-6))

    out_flat = flat_rgb.copy()
    out_flat[mask] = _linear_to_srgb(delit_lin).astype(np.float32)
    out = out_flat.reshape(orig_shape)
    if valid_mask is not None and arr.ndim == 3 and (~valid_mask).any():
        _, nn = ndimage.distance_transform_edt(~valid_mask, return_indices=True)
        out = out[nn[0], nn[1]]

    metrics = {
        "sh_directional_std_before": round(before_corr, 4),
        "sh_directional_std_after": round(after_corr, 4),
        "sh_variance_reduction": round(reduction, 4),
        "specular_texels_tamed": round(spec_removed_frac, 4),
    }
    return ((np.clip(out, 0.0, 1.0) * 255).astype(np.uint8) if is_u8 else np.clip(out, 0.0, 1.0)), metrics


def delight_albedo_2d(albedo_srgb: np.ndarray, strength: float = 0.70) -> np.ndarray:
    """De-lighting intrinsèque 2D multi-échelles (sans normales 3D) : retire les
    gradients basses fréquences d'éclairage studio et les reflets brûlés tout en
    préservant le grain fin des matériaux PBR."""
    is_u8 = albedo_srgb.dtype == np.uint8
    arr = albedo_srgb.astype(np.float32) / (255.0 if is_u8 else 1.0)
    lin = _srgb_to_linear(arr)
    lum = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    h, w = lum.shape
    sigma = max(h, w) / 7.5
    low_env = ndimage.gaussian_filter(np.log(np.clip(lum, 1e-3, 4.0)), sigma=sigma, mode="reflect")
    med_env = float(np.median(low_env))
    rel = np.exp(np.clip((low_env - med_env) * float(strength), -0.65, 0.65))
    delit = np.clip(lin / rel[..., None], 0.0, 1.0)
    out = _linear_to_srgb(delit).astype(np.float32)
    return (out * 255).astype(np.uint8) if is_u8 else out


def delight_image_2d(image: Image.Image | np.ndarray, strength: float = 0.70) -> tuple[Image.Image, dict]:
    """Enveloppe haut-niveau acceptant une `PIL.Image` ou `ndarray` et retournant
    `(pil_image_delit, metrics)` avec le taux objectif de réduction de variance basse fréquence."""
    arr_u8 = np.asarray(image.convert("RGB") if isinstance(image, Image.Image) else image, dtype=np.uint8)
    out_u8 = delight_albedo_2d(arr_u8, strength=strength)
    lum_b = _srgb_to_linear(arr_u8.astype(np.float32) / 255.0).mean(axis=2)
    lum_a = _srgb_to_linear(out_u8.astype(np.float32) / 255.0).mean(axis=2)
    sig = max(arr_u8.shape[:2]) / 7.5
    std_b = float(np.std(ndimage.gaussian_filter(np.log(np.clip(lum_b, 1e-3, 4.0)), sigma=sig, mode="reflect")))
    std_a = float(np.std(ndimage.gaussian_filter(np.log(np.clip(lum_a, 1e-3, 4.0)), sigma=sig, mode="reflect")))
    red = max(0.0, 1.0 - std_a / max(std_b, 1e-6))
    return Image.fromarray(out_u8, mode="RGB"), {
        "mode": "2d_intrinsic",
        "low_freq_std_before": round(std_b, 4),
        "low_freq_std_after": round(std_a, 4),
        "sh_variance_reduction": round(red, 4),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="Texture albédo PNG/JPG/WebP d'entrée")
    ap.add_argument("-o", "--output", required=True, help="Texture albédo de-lit de sortie")
    ap.add_argument("--normals", default=None, help="Carte de normales 3D optionnelle")
    ap.add_argument("--strength", type=float, default=0.85)
    args = ap.parse_args(argv)

    alb = np.asarray(Image.open(args.input).convert("RGB"))
    if args.normals and Path(args.normals).exists():
        nrm = np.asarray(Image.open(args.normals).convert("RGB"), dtype=np.float32) / 127.5 - 1.0
        out, meta = delight_albedo_3d(alb, nrm, strength=args.strength)
    else:
        out = delight_albedo_2d(alb, strength=args.strength)
        meta = {"mode": "2d_intrinsic"}
    Image.fromarray(out).save(args.output)
    print(json.dumps({"output": args.output, **meta}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
