#!/usr/bin/env python3
"""
game_ready.py — Pipeline Industriel d'Assets Temps Réel AAA (`3d-forge v5 — Game-Ready Edition`).

Transforme n'importe quelle recette CAO `Builder`, maillage High-Poly sculpté (`gpu_sculpt.py`)
ou fichier `.glb` en un **pack complet d'asset de jeu vidéo temps réel** prêt à glisser-déposer
dans **Unreal Engine 5**, **Unity (HDRP / URP)**, **Godot 4**, **Blender** ou **Three.js** :

  1. **Fusion intelligente des Draw Calls** : regroupe toutes les pièces statiques opaques en
     **1 seul Draw Call** (`SM_<Name>_Body`), garde 1 Draw Call verre réfractif + 1 par sous-groupe
     articulé mobile (`front_axle`, `lid`, `front_door`...), divisant par 20 à 100 les draw calls !
  2. **High-Poly -> Low-Poly Raycast / Surface-Projection Baker + Chaîne `LOD0 / LOD1 / LOD2`** :
     projette les normales 3D fines, l'Ambient Occlusion, la Courbure (`Curvature`) et les matériaux
     d'un maillage High-Poly (`40k - 150k tris`) dans l'espace tangent exact `TANGENT (VEC4)` d'un
     `LOD0` léger (`1 500 - 6 000 tris`), puis génère automatiquement `LOD1` (`40%`) et `LOD2` (`15%`).
  3. **PBR Réaliste Systématique (Scans GPU Datacenter + Patine 4 Couches + Normal Stamps)** :
     - Triplanar micro-grain issu des vrais scans matière GPU (`assets/ai_materials/*.png`),
     - **Curvature Edge Wear** (peinture écaillée révélant le métal brillant sur les arêtes vives),
     - **Cavity Dirt & Oil** (poussière/graisse mate logée dans les creux AO),
     - **World-Z Ground Grime** (salissure progressive près du sol `z = 0`),
     - **Normal Stamp Decals** (rainures de panneaux, boulons hexagonaux, rivets sans polygones).
  4. **Profils d'Export Natifs Multi-Moteurs (`--engine unreal | unity | godot | gltf | all`)** :
     - **Unreal Engine 5** : `T_<Name>_BC.png`, `T_<Name>_ORM.png`, **`T_<Name>_N.png` (DirectX `-Y` !)**
     - **Unity HDRP/URP** : `T_<Name>_BaseMap.png`, **`T_<Name>_MaskMap.png` (`RGBA`: Metal/AO/Detail/Smoothness)**, `T_<Name>_NormalGL.png` (`+Y`)
     - **Godot 4 / glTF** : `.glb` autonome compressé WebP (`EXT_texture_webp`), `TANGENT VEC4`, animations `gltf.animations` standards et enfants physiques `-colonly` / `UCX_*` !
  5. **Collisions Physiques Convexes (`UCX_<Name>_00..N` / `-colonly`) + Sockets Gameplay (`SOCKET_*`)**.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.spatial import cKDTree
import trimesh

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import delight as dl  # noqa: E402
import meshkit as mk  # noqa: E402
import pbr  # noqa: E402
import packager as pkg  # noqa: E402
import recipes  # noqa: E402
import renderer  # noqa: E402


# --------------------------------------------------------------------------- #
# 1. Chargement et projection triplanaire des scans matière GPU Datacenter
# --------------------------------------------------------------------------- #

_SCAN_CACHE: dict[str, np.ndarray] = {}


# Identifiants sémantiques de matériaux PBR (`v5.1+` — zéro métal/rivets sur surfaces propres !)
MAT_PAINTED_ARMOR = 0
MAT_BRUSHED_STEEL = 1
MAT_GOLD_BRONZE   = 2
MAT_RUBBER_POLY   = 3
MAT_WOOD_FABRIC   = 4
MAT_HAZARD_STRIPE = 5
MAT_TSUKA_WRAP    = 6
MAT_TAMAHAGANE    = 7
MAT_CLEAN_ENAMEL  = 8
MAT_REPTILE_SCALES = 9
MAT_WING_MEMBRANE = 10
MAT_BELLY_SCUTES  = 11
MAT_KERATIN_HORN  = 12

_ARMOR_KEYWORDS = (
    "armor", "hull", "crate", "container", "panel", "mech", "tank",
    "turret", "bunker", "ordnance", "scifi", "sci_fi", "chassis",
    "receiver", "bulkhead",
)


def classify_material_id(mat_use: mk.Material, part_label: str = "") -> int:
    """Déduit l'archétype physique exact d'une pièce à partir de son nom et de ses paramètres PBR."""
    nm = (getattr(mat_use, "name", "") + " " + part_label).lower()
    if any(k in nm for k in ("keratin_horn", "dragon_horn", "claw_keratin", "dorsal_spine")):
        return MAT_KERATIN_HORN
    if any(k in nm for k in ("belly_scute", "ventral_", "scutes")):
        return MAT_BELLY_SCUTES
    if any(k in nm for k in ("wing_membrane", "patagium")):
        return MAT_WING_MEMBRANE
    if any(k in nm for k in ("reptile_scale", "scaled_", "wyvern_hide", "dragon_wing_arm")):
        return MAT_REPTILE_SCALES
    if any(k in nm for k in ("tsuka", "ito_wrap", "hilt_wrap")):
        return MAT_TSUKA_WRAP
    if "blade" in nm:
        return MAT_TAMAHAGANE
    if any(k in nm for k in ("hazard", "chevron", "warning", "accent_stripe")):
        return MAT_HAZARD_STRIPE
    if any(k in nm for k in ("rubber", "tire", "grip", "knob", "boot", "skid", "bumper", "corner_cap", "vent")):
        return MAT_RUBBER_POLY
    if any(k in nm for k in ("wood", "fabric", "ito", "leather", "rope", "denim", "cloth", "wool")):
        return MAT_WOOD_FABRIC
    if any(k in nm for k in ("gold", "brass", "bronze", "copper", "menuki", "habaki", "seppa", "tsuba")):
        return MAT_GOLD_BRONZE
    # BUG CORRIGÉ (v5.8) : le mot-clé l'emportait sur la physique. Un rail
    # Picatinny en POLYMÈRE (`metallic = 0.0`, rough 0.62) partait en
    # « acier brossé » simplement parce que son nom contient « rail » — le
    # moteur lui appliquait alors un brossage anisotrope et des éclats d'acier
    # sur une pièce moulée. Le métal déclaré par le matériau passe d'abord.
    if float(getattr(mat_use, "metallic", 0.0)) >= 0.72:
        return MAT_BRUSHED_STEEL
    if float(getattr(mat_use, "metallic", 0.0)) <= 0.15 and any(
            k in nm for k in ("polymer", "polyamid", "nylon", "plastic", "resin",
                              "composite", "cerakote", "mag_", "rail")):
        return MAT_RUBBER_POLY
    if any(k in nm for k in ("steel", "chrome", "iron", "alu", "rail", "latch", "bolt", "hinge")):
        return MAT_BRUSHED_STEEL
    if any(k in nm for k in _ARMOR_KEYWORDS):
        return MAT_PAINTED_ARMOR
    return MAT_CLEAN_ENAMEL


def _load_material_scan(kind: str) -> np.ndarray | None:
    """Charge un vrai scan PBR sans couture généré sur le GPU Datacenter (`assets/ai_materials/`)."""
    mapping = {
        "metal_painted": "scifi_painted_metal.png",
        "polymer": "weathered_hazard_polymer.png",
        "steel": "forged_steel_micrograin.png",
        "tamahagane": "tamahagane_steel.png",
        "tsuka": "black_tsuka_wrap.png",
        "bronze": "antique_bronze.png",
        "rubber": "knobby_rubber.png",
        "rust": "rust_oxide.png",
        "leather": "worn_leather.png",
        "wood": "oak_wood.png",
    }
    fname = mapping.get(kind)
    if not fname:
        return None
    if fname not in _SCAN_CACHE:
        p = ROOT / "assets" / "ai_materials" / fname
        if not p.exists():
            return None
        arr = np.asarray(Image.open(p).convert("RGB"), dtype=np.float32) / 255.0
        # Extrait le grain haute/moyenne fréquence neutre en moyenne (= 1.0) pour moduler n'importe quelle teinte !
        lum = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
        low = ndimage.gaussian_filter(lum, sigma=max(arr.shape[:2]) / 9.0, mode="wrap")
        detail_ratio = np.clip(lum / np.maximum(low, 1e-3), 0.62, 1.42)
        _SCAN_CACHE[fname] = detail_ratio.astype(np.float32)
    return _SCAN_CACHE[fname]


def sample_triplanar_grain(pos: np.ndarray, nrm: np.ndarray, kind: str = "metal_painted",
                           tile_m: float = 0.28) -> np.ndarray:
    """Échantillonne sans couture (projection triplanaire pondérée par `|N|^4`) un scan
    matière GPU Datacenter en coordonnées monde métriques `pos (N, 3)`."""
    scan = _load_material_scan(kind)
    if scan is None:
        return np.ones(len(pos), dtype=np.float32)
    h, w = scan.shape
    an = np.abs(nrm) ** 4.0
    an /= np.sum(an, axis=1, keepdims=True) + 1e-8

    def _fetch(u_coord: np.ndarray, v_coord: np.ndarray) -> np.ndarray:
        ix = np.mod(np.floor(u_coord / tile_m * w).astype(np.int32), w)
        iy = np.mod(np.floor(v_coord / tile_m * h).astype(np.int32), h)
        return scan[iy, ix]

    gx = _fetch(pos[:, 1], pos[:, 2])
    gy = _fetch(pos[:, 0], pos[:, 2])
    gz = _fetch(pos[:, 0], pos[:, 1])
    return (an[:, 0] * gx + an[:, 1] * gy + an[:, 2] * gz).astype(np.float32)


# --------------------------------------------------------------------------- #
# 2. Normal Stamp Decals (panneaux industriels, rivets, boulons 0-polygone)
# --------------------------------------------------------------------------- #

def stamp_normal_decals(
    pos: np.ndarray,
    nrm: np.ndarray,
    metal: np.ndarray,
    bounds: np.ndarray,
    panel_spacing: float = 0.16,
    strength: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Génère sans aucun polygone supplémentaire une carte de hauteur analytique
    de rainures d'usinage/panneaux + têtes de rivets circulaires sur les surfaces
    métalliques/polymères planes. Retourne `(delta_height, ao_mult, metal_boost)`."""
    span = float(np.max(bounds[1] - bounds[0]))
    sp = max(panel_spacing, span * 0.16)
    an = np.abs(nrm)
    dom_axis = np.argmax(an, axis=1)

    # Coordonnées 2D locales sur la face dominante de chaque texel
    u = np.where(dom_axis == 0, pos[:, 1], pos[:, 0])
    v = np.where(dom_axis == 2, pos[:, 1], pos[:, 2])

    fu = np.abs((u / sp) - np.round(u / sp)) * sp
    fv = np.abs((v / sp) - np.round(v / sp)) * sp
    groove_w = max(0.0018, sp * 0.014)

    # Rainures fines chanfreinées entre panneaux
    g_u = np.exp(-((fu / groove_w) ** 2))
    g_v = np.exp(-((fv / groove_w) ** 2))
    groove = np.maximum(g_u, g_v)

    # Rivets / vis BTR logés près des coins de panneaux
    cu = np.abs(fu - groove_w * 3.8)
    cv = np.abs(fv - groove_w * 3.8)
    r_dist = np.hypot(cu, cv)
    rivet_r = groove_w * 1.45
    rivet_dome = np.clip(1.0 - (r_dist / max(rivet_r, 1e-5)) ** 2, 0.0, 1.0)
    rivet_ring = np.exp(-(((r_dist - rivet_r * 1.15) / max(groove_w * 0.45, 1e-5)) ** 2))

    hard_surface = np.clip(0.35 + 0.65 * metal, 0.0, 1.0) * float(strength)
    d_height = (-0.55 * groove + 0.48 * rivet_dome - 0.22 * rivet_ring) * hard_surface
    ao_mult = np.clip(1.0 - 0.28 * groove * hard_surface - 0.14 * rivet_ring * hard_surface, 0.55, 1.0)
    metal_boost = np.clip(0.45 * rivet_dome * hard_surface, 0.0, 0.6)
    return d_height.astype(np.float32), ao_mult.astype(np.float32), metal_boost.astype(np.float32)


# --------------------------------------------------------------------------- #
# 3. Patine Physique Game-Ready 4 Couches (Edge Wear + Cavity Dirt + Ground Grime)
# --------------------------------------------------------------------------- #

def compress_albedo_headroom(col: np.ndarray, knee: float = 0.72,
                             cap: float = 0.86) -> np.ndarray:
    """Garantit une RÉSERVE de dynamique à un albédo diffus (v5.7).

    Aucun matériau diffus ne réfléchit ~100 % de la lumière : le plus blanc
    (porcelaine émaillée, ivoire, ABS blanc) plafonne autour de 0.80. Les
    recettes utilisaient des blancs à 0.90-0.96 ; au-delà, le grain
    multiplicatif et les variations macro étaient CLIPPÉS à 1.0 (la moitié de
    la dynamique perdue) et la tonemap n'avait plus de place pour modeler la
    surface. Mesuré sur le pion d'échecs : luminance médiane 0.945, dynamique
    du rendu 0.09 -> 0.17 après correction.

    Compression C1 : identité jusqu'à `knee`, tanh au-delà (f(knee)=knee,
    f'(knee)=1) : aucune cassure visible dans les dégradés.
    """
    col = np.asarray(col, dtype=np.float32)
    out = np.where(col < knee, col, knee + (cap - knee) * np.tanh((col - knee) / (cap - knee)))
    return np.clip(out, 0.0, cap).astype(np.float32)


def apply_game_weathering(
    col: np.ndarray,
    rough: np.ndarray,
    metal: np.ndarray,
    ao: np.ndarray,
    curv: np.ndarray,
    pos: np.ndarray,
    nrm: np.ndarray,
    bounds: np.ndarray,
    mat_id: np.ndarray | None = None,
    wear_amount: float = 0.52,
    dirt_amount: float = 0.36,
    grime_amount: float = 0.22,
    decal_strength: float = 0.55,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Moteur de patine PBR sémantique par matériau (`v5.1`) :
      - `MAT_PAINTED_ARMOR` : préserve 95 % d'émail riche & profond + éclats d'acier
        uniquement sur les vraies arêtes vives (`curv > 0.56`, zéro tache grise boueuse !),
      - `MAT_HAZARD_STRIPE` : chevrons industriels diagonaux 45° noir/ambre ultra-nets + micro-rayures,
      - `MAT_BRUSHED_STEEL` : micro-brossage linéaire anisotrope + reflets acier vif,
      - `MAT_GOLD_BRONZE`   : patine antique sombre dans les cavités d'AO + crêtes polies `0.17`,
      - `MAT_RUBBER_POLY`   : caoutchouc / polymère mat strict (`metallic == 0.0` garanti !),
      - `MAT_WOOD_FABRIC`   : grain organique / textile sans aucun reflet métallique parasite.
    """
    col = col.astype(np.float32).copy()
    rough = rough.astype(np.float32).copy()
    metal = metal.astype(np.float32).copy()
    ao = ao.astype(np.float32).copy()

    # ---- v5.7 : budget d'albédo physique --------------------------------
    # Aucun matériau diffus ne réfléchit ~100 % de la lumière : le plus blanc
    # (porcelaine émaillée, ivoire, plastique ABS blanc) plafonne autour de 0.80.
    # Les recettes utilisaient des blancs à 0.90-0.96 : au-delà, le grain
    # multiplicatif et les variations macro étaient CLIPPÉS à 1.0 (moitié de la
    # dynamique perdue) et ACES n'avait plus de place pour modeler la surface.
    # Mesure sur le pion d'échecs avant : luminance médiane 0.945, dynamique 0.09.
    # On compresse doucement le dessus de l'échelle en gardant les ratios.
    if col.size:
        lum_col = col @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        hi = float(np.percentile(lum_col, 99.0))
        if hi > 0.86:
            # compression douce : les valeurs < 0.72 restent intactes, le haut
            # de l'échelle converge vers 0.86 sans créer de plateau (tanh).
            k, cap = 0.72, 0.86
            # f(k) = k et f'(k) = 1 : continuité C1, aucune cassure de dégradé.
            col = np.where(col < k, col,
                           k + (cap - k) * np.tanh((col - k) / (cap - k)))
            col = np.clip(col, 0.0, cap)

    if mat_id is None:
        mat_id = np.where(metal > 0.72, MAT_BRUSHED_STEEL,
                          np.where(rough > 0.68, MAT_RUBBER_POLY, MAT_PAINTED_ARMOR)).astype(np.int32)
    else:
        mat_id = np.asarray(mat_id, dtype=np.int32)

    span = np.maximum(bounds[1] - bounds[0], 1e-4)
    tile_m = float(np.clip(span.max() * 0.30, 0.05, 0.50))

    is_rubber = mat_id == MAT_RUBBER_POLY
    is_wood   = mat_id == MAT_WOOD_FABRIC
    is_gold   = mat_id == MAT_GOLD_BRONZE
    is_steel  = (mat_id == MAT_BRUSHED_STEEL) | (mat_id == MAT_TAMAHAGANE)
    is_blade  = mat_id == MAT_TAMAHAGANE
    is_tsuka  = mat_id == MAT_TSUKA_WRAP
    is_hazard = mat_id == MAT_HAZARD_STRIPE
    is_clean  = mat_id == MAT_CLEAN_ENAMEL
    is_nonmetal = is_rubber | is_wood | is_tsuka
    # Sauvegarde les valeurs pures des surfaces propres (peau, céramique, émail, vernis auto, yeux)
    col_clean_src = col.copy()
    rgh_clean_src = rough.copy()
    mtl_clean_src = metal.copy()
    extra_h = np.zeros(len(pos), dtype=np.float32)

    # 0a. Tressage japonais `tsuka-maki` ultra-haute définition (évalué au pixel exact 1024² !)
    if is_tsuka.any():
        px_t, py_t, pz_t = pos[is_tsuka, 0], pos[is_tsuka, 1], pos[is_tsuka, 2]
        ang = np.arctan2(py_t, px_t) / math.pi  # [-1..1]
        turns = pz_t / 0.0275
        u1 = np.abs(np.mod(turns + ang * 0.5, 1.0) * 2.0 - 1.0)
        u2 = np.abs(np.mod(turns - ang * 0.5, 1.0) * 2.0 - 1.0)
        rib1 = np.clip((0.64 - u1) / 0.05, 0.0, 1.0)
        rib2 = np.clip((0.64 - u2) / 0.05, 0.0, 1.0)
        silk_mask = np.maximum(rib1, rib2)
        # Micro-tissage chevron de la tresse de soie noire/indigo + nodules blancs de `samegawa` !
        weave = 0.5 + 0.5 * np.sin((turns * 46.0 + ang * 18.0) * math.pi)
        pearls = 0.5 + 0.5 * np.sin(px_t * 2100.0) * np.sin(pz_t * 2100.0 + py_t * 1700.0)
        silk_col = np.array([0.075, 0.082, 0.105], dtype=np.float32)[None, :] * (0.82 + 0.36 * weave[:, None])
        # ivoire vieilli (0.72) plutôt que blanc pur : à l'échelle de rendu, un
        # galuchat à 0.86 se lisait comme du plastique blanc.
        same_col = np.array([0.72, 0.70, 0.64], dtype=np.float32)[None, :] * (0.80 + 0.22 * pearls[:, None])
        # Ombre portée réaliste sous le ruban au bord des fenêtres de galuchat !
        window_ao = np.clip(0.52 + 0.48 * np.minimum(np.abs(u1 - 0.64), np.abs(u2 - 0.64)) / 0.18, 0.52, 1.0)
        col[is_tsuka] = same_col * window_ao[:, None] * (1.0 - silk_mask[:, None]) + silk_col * silk_mask[:, None]
        rough[is_tsuka] = np.where(silk_mask > 0.5, 0.68 - 0.10 * weave, 0.36 + 0.12 * pearls)
        metal[is_tsuka] = 0.0
        extra_h[is_tsuka] = 0.42 * silk_mask + 0.08 * weave * silk_mask + 0.09 * pearls * (1.0 - silk_mask)

    # 0b. Acier forgé `tamahagane` + ligne de trempe ondulée `notare-choji hamon` au pixel exact 1024² !
    if is_blade.any():
        bx, bz = pos[is_blade, 0], pos[is_blade, 2]
        wave = 0.0022 * np.sin(bz * 82.0) + 0.0011 * np.sin(bz * 195.0 + 1.1)
        edge_dist = bx + wave  # > 0 côté tranchant `ha` !
        yakiba = np.clip((edge_dist - 0.0032) / 0.0022, 0.0, 1.0)
        habuchi = np.exp(-(((edge_dist - 0.0032) / 0.0014) ** 2))  # liseré blanc laiteux `nioi` !
        # Physique de la trempe : le `ji` (corps non trempé) est un miroir, le `ha`
        # (tranchant martensitique) est plus mat et moins métallique. Les deux valeurs
        # étaient inversées (tranchant metal 0.95 / rough 0.10) : la lame réfléchissait
        # l'environnement à pleine énergie, ACES écrasait tout à ~0.89 et le `hamon`
        # devenait invisible (écart-type de luminance mesuré : 0.04).
        ji_col = np.array([0.58, 0.61, 0.65], dtype=np.float32)[None, :]
        ha_col = np.array([0.80, 0.82, 0.85], dtype=np.float32)[None, :]
        nioi_col = np.array([0.93, 0.94, 0.96], dtype=np.float32)[None, :]
        c_bl = ji_col * (1.0 - yakiba[:, None]) + ha_col * yakiba[:, None]
        col[is_blade] = np.clip(c_bl * (1.0 - 0.55 * habuchi[:, None]) + nioi_col * (0.55 * habuchi[:, None]), 0.0, 1.0)
        # Laminage : ondulation lente de teinte le long de la soie (acier plié).
        fold = 1.0 + 0.045 * np.sin(bz * 34.0) + 0.022 * np.sin(bz * 91.0 + 0.7)
        col[is_blade] *= fold[:, None]
        rough[is_blade] = np.clip(0.17 * (1.0 - yakiba) + 0.40 * yakiba + 0.10 * habuchi, 0.10, 0.55)
        metal[is_blade] = np.clip(0.96 * (1.0 - yakiba) + 0.80 * yakiba, 0.0, 1.0)
        extra_h[is_blade] = 0.16 * habuchi + 0.035 * yakiba

    # 0. Motifs graphiques procéduraux nets : chevrons diagonaux 45° sur `MAT_HAZARD_STRIPE` !
    if is_hazard.any():
        stripe_phase = (pos[is_hazard, 0] + pos[is_hazard, 2] + pos[is_hazard, 1] * 0.35) / 0.052
        saw = np.abs(np.mod(stripe_phase, 1.0) * 2.0 - 1.0)
        black_band = np.clip((saw - 0.46) / 0.07, 0.0, 1.0)  # transition anti-aliasée ultra-nette !
        dark_stripe = np.array([0.09, 0.095, 0.105], dtype=np.float32)
        col[is_hazard] = col[is_hazard] * (1.0 - 0.88 * black_band[:, None]) + dark_stripe[None, :] * (0.88 * black_band[:, None])
        rough[is_hazard] = np.clip(rough[is_hazard] + 0.18 * black_band, 0.08, 1.0)
        metal[is_hazard] *= (1.0 - 0.75 * black_band)

    # 1. Micro-grain triplanaire issu des scans GPU Datacenter (calibré fin, zéro boue grise !)
    g_steel = sample_triplanar_grain(pos, nrm, "steel", tile_m=tile_m * 0.65)
    g_paint = sample_triplanar_grain(pos, nrm, "metal_painted", tile_m=tile_m)
    g_rub   = sample_triplanar_grain(pos, nrm, "rubber", tile_m=tile_m * 0.45)
    grain = np.where(is_steel | is_gold, g_steel, np.where(is_nonmetal, g_rub, g_paint))
    # v5.8 — amplitude bornée par famille. Sur un polymère moulé, le grain
    # triplanaire d'un scan acier projeté sur une grande face plane produit des
    # TACHES GRISES À BORDS NETS (mesuré : écart-type d'albédo 22 pour une photo
    # à 17 sur le même flanc). Un polymère reçoit un grain fin, un métal garde
    # son amplitude.
    g_amp = np.where(is_nonmetal, 0.055, 0.14)[:, None]
    col = col * np.clip(0.93 + g_amp * grain[:, None], 0.78, 1.18)
    rough = np.clip(rough * (1.09 - 0.18 * grain), 0.05, 1.0)

    # Brossage anisotrope fin sur acier (`MAT_BRUSHED_STEEL`)
    if is_steel.any():
        aniso = pbr.fbm(pos[is_steel, 0] * (85.0 / tile_m),
                        pos[is_steel, 1] * (12.0 / tile_m),
                        pos[is_steel, 2] * (85.0 / tile_m), octaves=2, seed=37).astype(np.float32)
        col[is_steel] *= (0.92 + 0.16 * aniso[:, None])
        rough[is_steel] = np.clip(rough[is_steel] * (1.12 - 0.26 * aniso), 0.06, 0.65)

    # 1bis. VARIATION À GRANDE ÉCHELLE (v5.6) — un émail uniforme fait « objet
    #       imprimé ». Trois couches physiquement motivées, toutes très basse
    #       fréquence pour ne pas concurrencer les micro-détails :
    #         a) dérive de teinte : les panneaux peints séparément ne sortent
    #            jamais exactement du même bain (LOT / UV sun-fade) ;
    #         b) poussière verticale : elle se dépose sur les surfaces tournées
    #            vers le haut (+Z) et jamais sous l'objet ;
    #         c) micro-nuance de peinture : très légère, casse l'aplat.
    macro = pbr.fbm(pos[:, 0] * (2.6 / tile_m), pos[:, 1] * (2.6 / tile_m),
                    pos[:, 2] * (1.7 / tile_m), octaves=3, seed=91).astype(np.float32)
    lot = np.clip(0.5 + (macro - 0.5) * 1.15, 0.0, 1.0)
    tint_drift = np.stack([0.94 + 0.13 * lot,
                           0.96 + 0.09 * lot,
                           0.92 + 0.10 * (1.0 - lot)], axis=1).astype(np.float32)
    col = np.where(is_nonmetal[:, None], col, np.clip(col * tint_drift, 0.0, 1.0))

    up_facing = np.clip(nrm[:, 2], 0.0, 1.0) ** 1.35
    dust_fbm = pbr.fbm(pos[:, 0] * (3.4 / tile_m), pos[:, 1] * (3.4 / tile_m),
                       pos[:, 2] * (9.0 / tile_m), octaves=3, seed=23).astype(np.float32)
    dust = np.clip(up_facing * (0.35 + 0.85 * dust_fbm) * 0.16, 0.0, 0.20)
    dust_col = np.array([0.33, 0.315, 0.285], dtype=np.float32)
    col = col * (1.0 - dust[:, None]) + dust_col[None, :] * dust[:, None]
    rough = np.clip(rough + 0.14 * dust, 0.05, 1.0)

    micro = pbr.fbm(pos[:, 0] * (11.0 / tile_m), pos[:, 1] * (11.0 / tile_m),
                    pos[:, 2] * (11.0 / tile_m), octaves=2, seed=53).astype(np.float32)
    col *= np.clip(0.955 + 0.09 * micro[:, None], 0.88, 1.06)

    # 2. Usure d'arêtes par courbure — v5.6 : usure COHÉRENTE sur les arêtes
    #    EXPOSÉES. Deux défauts corrigés (mesurés : 6,3 % de pixels blancs
    #    dispersés sur des panneaux plats) :
    #      a) le `breakup` était à 32 cycles/tile_m -> moucheture haute fréquence
    #         (« neige » blanche) au lieu d'éclats reliés ; on descend à 7 + 22 ;
    #      b) la courbure est forte sur TOUS les chanfreins d'un union CSG, y
    #         compris ceux enterrés dans les cavités : on gate par l'exposition
    #         (AO), donc l'usure n'apparaît que sur les arêtes qui voient le jour.
    breakup = pbr.fbm(pos[:, 0] * (7.0 / tile_m), pos[:, 1] * (7.0 / tile_m),
                      pos[:, 2] * (7.0 / tile_m), octaves=3, seed=71).astype(np.float32)
    breakup_fine = pbr.fbm(pos[:, 0] * (22.0 / tile_m), pos[:, 1] * (22.0 / tile_m),
                           pos[:, 2] * (22.0 / tile_m), octaves=2, seed=17).astype(np.float32)
    breakup = np.clip(0.60 * breakup + 0.40 * breakup_fine, 0.0, 1.0)
    sharp_edge = np.clip((curv - 0.54) / 0.34, 0.0, 1.0) ** 1.6
    exposure = np.clip((ao - 0.42) / 0.58, 0.0, 1.0) ** 1.15
    edge_mask = np.clip(sharp_edge * exposure
                        * np.clip(0.25 + 1.05 * breakup, 0.0, 1.0) * wear_amount,
                        0.0, 0.62)

    # Sur métal peint / chevrons : éclats d'acier poli ; sur caoutchouc : frottement mat gris sombre (`metal=0`) !
    bare_steel = np.array([0.78, 0.80, 0.83], dtype=np.float32)
    scuff_rubber = np.array([0.27, 0.28, 0.30], dtype=np.float32)
    bright_gold = np.clip(col * 1.28 + 0.06, 0.0, 1.0)
    # v5.7 — une peinture SATURÉE ne s'use pas jusqu'à l'acier gris : la couche
    # pigmentée s'éclaircit d'abord, l'apprêt reste teinté. Mesuré sur la fusée :
    # la jonction cône/fût sortait à un albédo neutre de 0.787 (de l'acier) au
    # milieu d'un rouge à 0.68/0.61/0.60 — la « couture déchirée » n'était pas
    # une couture UV mais cet éclat gris. On interpole donc l'éclat vers un
    # éclaircissement de la teinte selon la saturation de la peinture.
    _mx = col.max(axis=1)
    _mn = col.min(axis=1)
    sat_c = np.clip((_mx - _mn) / np.maximum(_mx, 1e-4), 0.0, 1.0)
    pale_paint = np.clip(col * 1.30 + 0.10, 0.0, 1.0)
    w_st = np.clip((sat_c - 0.30) / 0.35, 0.0, 1.0) ** 1.1
    steel_edge = bare_steel[None, :] * (1.0 - w_st[:, None]) + pale_paint * w_st[:, None]
    # v5.8 — un acier PHOSPHATÉ (canon, frein de bouche, rails) est noir mat :
    # lui appliquer l'acier nu à 0.78 le faisait briller comme du chrome poli
    # (p95 d'albédo mesuré à 138 pour une photo à 75). L'usure d'une pièce
    # sombre reste sombre : on éclaircit la teinte de base au lieu de la
    # remplacer par du métal nu.
    lum_b = col @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    dark_metal = np.clip((0.30 - lum_b) / 0.20, 0.0, 1.0)[:, None]
    steel_edge = steel_edge * (1.0 - dark_metal) + np.clip(col * 1.55 + 0.045, 0.0, 1.0) * dark_metal
    target_edge = np.where(
        is_nonmetal[:, None], scuff_rubber[None, :],
        np.where(is_gold[:, None], bright_gold, steel_edge),
    )
    eff_edge = np.where(is_nonmetal, edge_mask * 0.42, edge_mask)
    # Le jaune sécurité est une peinture fraîche et réfléchissante : on limite
    # fortement l'éclat d'usure dessus, sinon il vire au brun sale.
    eff_edge = np.where(is_hazard, eff_edge * 0.35, eff_edge)
    col = col * (1.0 - eff_edge[:, None]) + target_edge * eff_edge[:, None]
    metal = np.where(is_nonmetal, 0.0, np.clip(metal + eff_edge * 0.82, 0.0, 1.0))
    rough = np.where(
        is_nonmetal,
        np.clip(rough + 0.10 * eff_edge, 0.25, 1.0),
        np.clip(rough * (1.0 - 0.60 * eff_edge) + 0.15 * eff_edge, 0.05, 1.0),
    )

    # 3. Crasse et patine antique dans les cavités profondes d'AO uniquement (`ao < 0.60`)
    # v5.6 — la crasse ne doit pas désaturer l'objet : plafond 0.34 au lieu de
    # 0.52 (27 % de la texture était sous AO 0.5, d'où un rendu « boueux »).
    # v5.7 — la crasse n'est PAS neutre sur une matière claire : sur une
    # porcelaine ou un ivoire (albédo > 0.55), la même quantité de terre se lit
    # comme de la saleté et bascule l'objet du blanc vers le beige sale. On la
    # dose donc selon la clarté de base : pleine sur les matières sombres et les
    # métaux, fortement réduite sur les blancs (qui sont des produits d'intérieur
    # propres, pas des caisses de chantier).
    lum_base = col @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    pale = np.clip((lum_base - 0.55) / 0.30, 0.0, 1.0) ** 1.2
    dirt_scale = 1.0 - 0.62 * pale
    cavity = np.clip((0.52 - ao) * 1.35 * (0.50 + 0.60 * breakup) * dirt_amount
                     * dirt_scale, 0.0, 0.34)
    dirt_col = np.where(
        is_gold[:, None],
        np.array([[0.15, 0.125, 0.085]], dtype=np.float32),
        np.array([[0.12, 0.115, 0.11]], dtype=np.float32),
    )
    col = col * (1.0 - cavity[:, None]) + dirt_col * cavity[:, None]
    rough = np.clip(rough + 0.26 * cavity, 0.05, 1.0)
    metal = np.where(is_nonmetal, 0.0, np.clip(metal * (1.0 - 0.50 * cavity), 0.0, 1.0))

    # 4. Salissure subtile de contact au sol (`World-Z Ground Grime`)
    z_norm = np.clip((pos[:, 2] - bounds[0][2]) / float(span[2]), 0.0, 1.0)
    grime = np.clip(np.exp(-z_norm / 0.065) * (0.35 + 0.60 * breakup) * grime_amount
                    * dirt_scale, 0.0, 0.30)
    earth_col = np.array([0.19, 0.17, 0.145], dtype=np.float32)
    col = col * (1.0 - grime[:, None]) + earth_col[None, :] * grime[:, None]
    rough = np.clip(rough + 0.18 * grime, 0.05, 1.0)

    # 5. Normal Stamp Decals strictement réservés aux panneaux industriels/blindés !
    can_stamp = mat_id == MAT_PAINTED_ARMOR
    dh, ao_m, m_boost = stamp_normal_decals(pos, nrm, np.where(can_stamp, metal, 0.0), bounds, strength=decal_strength)
    dh = np.where(can_stamp, dh, 0.0)
    ao_m = np.where(can_stamp, ao_m, 1.0)
    ao = np.clip(ao * ao_m, 0.12, 1.0)
    metal = np.where(is_nonmetal, 0.0, np.clip(metal + np.where(can_stamp, m_boost * 0.28, 0.0), 0.0, 1.0))
    chevron_h = np.zeros_like(dh)
    if is_hazard.any():
        chevron_h[is_hazard] = 0.08
    height = (0.24 * (grain - 1.0) - 0.15 * eff_edge + dh + chevron_h + extra_h).astype(np.float32)

    # 6. Finition Studio Propre (`MAT_CLEAN_ENAMEL` : céramique, émail, peau, figurines,
    #    peintures vives, carrosserie vernie) — ZÉRO boue brune, ZÉRO éclat gris acier,
    #    ZÉRO rivet sci-fi, ZÉRO dérive de teinte sale, micro-glaçure subtile naturelle !
    if is_clean.any():
        glaze_macro = (macro[is_clean] - 0.5) * 0.10
        glaze_micro = (micro[is_clean] - 0.5) * 0.10
        soft_grad = (z_norm[is_clean] - 0.5) * 0.055
        # Centré à 0.955 pour ne jamais saturer contre le plafond 0.86 sur blanc/verre clair !
        soft_shade = np.clip(0.955 + glaze_macro + glaze_micro + soft_grad, 0.86, 1.01)[:, None]
        col[is_clean] = np.clip(col_clean_src[is_clean] * soft_shade, 0.0, 0.86)
        rough[is_clean] = np.clip(
            rgh_clean_src[is_clean] + 0.075 * (0.5 - micro[is_clean]) + 0.06 * np.clip(0.55 - ao[is_clean], 0.0, 0.4),
            0.03, 1.0,
        )
        metal[is_clean] = np.clip(mtl_clean_src[is_clean], 0.0, 1.0)
        height[is_clean] = (0.14 * (micro[is_clean] - 0.5) + 0.06 * (macro[is_clean] - 0.5)).astype(np.float32)

    # 7. Écailles reptiliennes organiques mates (`MAT_REPTILE_SCALES` : fines, distordues & sans reflet plastique !)
    is_reptile = mat_id == MAT_REPTILE_SCALES
    if is_reptile.any():
        pr = pos[is_reptile]
        nr = nrm[is_reptile]
        an = np.abs(nr)
        w3 = an / np.maximum(an.sum(axis=1, keepdims=True), 1e-6)
        freq_s = 1.0 / np.clip(float(span.max()) * 0.0115, 0.0045, 0.010)

        def _tex_hex_scales(u_c: np.ndarray, v_c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            # Distorsion organique douce pour briser tout alignement en grille « épi de maïs » !
            uw = u_c + 0.0055 * np.sin(v_c * 37.0 + u_c * 19.0)
            vw = v_c + 0.0045 * np.cos(u_c * 31.0 - v_c * 23.0)
            row = vw * freq_s * 1.18
            row_i = np.floor(row)
            fu = uw * freq_s + 0.5 * np.mod(row_i, 2.0)
            du = np.mod(fu, 1.0) - 0.5
            dv = np.mod(row, 1.0) - 0.5
            # Losange reptilien effilé (pas de bille ronde !)
            d = np.abs(du) * 1.32 + np.abs(dv + 0.08) * 1.12
            dome = np.clip(1.0 - (d / 0.62) ** 1.35, 0.0, 1.0)
            crevice = np.clip((d - 0.44) / 0.18, 0.0, 1.0)
            return dome, crevice

        d_yz, c_yz = _tex_hex_scales(pr[:, 1], pr[:, 2])
        d_xz, c_xz = _tex_hex_scales(pr[:, 0], pr[:, 2])
        d_xy, c_xy = _tex_hex_scales(pr[:, 0], pr[:, 1])
        s_dome = w3[:, 0] * d_yz + w3[:, 1] * d_xz + w3[:, 2] * d_xy
        s_crev = w3[:, 0] * c_yz + w3[:, 1] * c_xz + w3[:, 2] * c_xy

        warm_gold = np.array([0.66, 0.42, 0.22], dtype=np.float32)
        dark_blood = np.array([0.14, 0.045, 0.02], dtype=np.float32)
        base_c = col_clean_src[is_reptile]
        bronze_kiss = np.clip(0.28 * (s_dome ** 1.6) + 0.34 * (macro[is_reptile] - 0.32), 0.0, 0.58)[:, None]
        lit_scale = base_c * (1.0 - bronze_kiss) + warm_gold[None, :] * bronze_kiss
        col[is_reptile] = lit_scale * (1.0 - 0.68 * s_crev[:, None]) + dark_blood[None, :] * (0.68 * s_crev[:, None])
        ao[is_reptile] = np.clip(ao[is_reptile] * (1.0 - 0.42 * s_crev), 0.16, 1.0)
        # Kératine reptilienne mate-satinée (`0.48..0.78`) : ZÉRO point blanc spéculaire plastique !
        rough[is_reptile] = np.clip(0.54 + 0.24 * s_crev - 0.06 * s_dome, 0.46, 0.86)
        metal[is_reptile] = 0.0
        height[is_reptile] = (0.72 * (s_dome - 0.45) - 0.38 * s_crev + 0.14 * (micro[is_reptile] - 0.5)).astype(np.float32)

    # 8. Plaques ventrales segmentées ocre-or (`MAT_BELLY_SCUTES`)
    is_scute = mat_id == MAT_BELLY_SCUTES
    if is_scute.any():
        ps_v = pos[is_scute]
        band_phase = np.mod((ps_v[:, 2] * 38.0 - ps_v[:, 1] * 14.0), 1.0)
        seam = np.exp(-((band_phase / 0.14) ** 2)) + np.exp(-(((1.0 - band_phase) / 0.10) ** 2))
        seam = np.clip(seam, 0.0, 1.0)
        ochre_hi = np.array([0.74, 0.54, 0.31], dtype=np.float32)
        umber_lo = np.array([0.24, 0.11, 0.05], dtype=np.float32)
        shade_s = np.clip(0.45 + 0.55 * band_phase * (0.7 + 0.3 * macro[is_scute]), 0.0, 1.0)[:, None]
        sc_col = col_clean_src[is_scute] * 0.55 + ochre_hi[None, :] * 0.45 * shade_s
        col[is_scute] = sc_col * (1.0 - 0.72 * seam[:, None]) + umber_lo[None, :] * (0.72 * seam[:, None])
        ao[is_scute] = np.clip(ao[is_scute] * (1.0 - 0.45 * seam), 0.18, 1.0)
        rough[is_scute] = np.clip(0.50 + 0.25 * seam, 0.42, 0.82)
        metal[is_scute] = 0.0
        height[is_scute] = (0.55 * band_phase - 0.65 * seam).astype(np.float32)

    # 9. Membrane d'aile cuirasse parcheminée veinée (`MAT_WING_MEMBRANE`)
    is_wing = mat_id == MAT_WING_MEMBRANE
    if is_wing.any():
        pw = pos[is_wing]
        vein_f = np.abs(np.sin((pw[:, 1] * 26.0 + pw[:, 2] * 19.0 + 1.8 * macro[is_wing]) * math.pi))
        veins = np.clip(1.0 - vein_f / 0.16, 0.0, 1.0)
        parchment = np.array([0.65, 0.42, 0.25], dtype=np.float32)
        dark_umbr = np.array([0.24, 0.10, 0.05], dtype=np.float32)
        mottled = np.clip(0.32 + 0.68 * macro[is_wing] * (0.55 + 0.45 * micro[is_wing]), 0.0, 1.0)[:, None]
        w_col = dark_umbr[None, :] * (1.0 - mottled) + parchment[None, :] * mottled
        col[is_wing] = w_col * (1.0 - 0.45 * veins[:, None]) + dark_umbr[None, :] * (0.45 * veins[:, None])
        rough[is_wing] = np.clip(0.62 - 0.10 * veins + 0.12 * (micro[is_wing] - 0.5), 0.44, 0.88)
        metal[is_wing] = 0.0
        height[is_wing] = (0.42 * veins + 0.18 * (macro[is_wing] - 0.5)).astype(np.float32)

    # 10. Cornes, griffes & épines de kératine striées (`MAT_KERATIN_HORN` : base sombre acajou -> pointe os vieilli)
    is_horn = mat_id == MAT_KERATIN_HORN
    if is_horn.any():
        ph = pos[is_horn]
        # Anneaux de croissance transversaux le long de la corne + dégradé organique racine sombre -> pointe dorée
        ring_p = np.sin((ph[:, 1] * 145.0 + ph[:, 2] * 125.0 + 1.5 * micro[is_horn]) * math.pi)
        rings = 0.5 + 0.5 * ring_p
        dark_root = np.array([0.19, 0.075, 0.04], dtype=np.float32)
        bone_tip = np.array([0.74, 0.56, 0.37], dtype=np.float32)
        tip_t = np.clip(0.30 + 0.65 * ao[is_horn] + 0.22 * (macro[is_horn] - 0.4), 0.0, 1.0)[:, None]
        h_col = dark_root[None, :] * (1.0 - tip_t) + bone_tip[None, :] * tip_t
        col[is_horn] = h_col * (0.80 + 0.26 * rings[:, None])
        rough[is_horn] = np.clip(0.46 + 0.22 * (1.0 - rings), 0.34, 0.78)
        metal[is_horn] = 0.0
        height[is_horn] = (0.45 * (rings - 0.5) + 0.12 * (micro[is_horn] - 0.5)).astype(np.float32)

    # v5.6 — contrainte DURE en sortie : les additifs (éclats, decals, boosts)
    # pouvaient rendre métallique une famille qui ne doit jamais l'être. Mesuré
    # sur le katana : soie `tsuka` à metallic 0.54 dans l'ORM -> la poignée
    # reflétait le studio en gris argenté au lieu de rester de la soie noire.
    metal = np.where(is_nonmetal, 0.0, metal)
    rough = np.where(is_tsuka, np.clip(rough, 0.45, 1.0), rough)

    # v5.7 — INVARIANT D'ALBÉDO en sortie : la compression posée en entrée peut
    # être défaite par le grain, la poussière et les macro-variations
    # multiplicatives (mesuré : 0.873 de luminance médiane sur le pion d'échecs,
    # alors que la compression visait 0.86). On garantit ici le budget de
    # headroom : aucun diffus ne renvoie ~100 % de la lumière.
    col = compress_albedo_headroom(np.clip(col, 0.0, 1.0))
    return col, rough, metal, ao, height


# --------------------------------------------------------------------------- #
# 4. High-Poly -> Low-Poly Tangent-Space Baker & Génération `LOD0 / LOD1 / LOD2`
# --------------------------------------------------------------------------- #

import threading
_FAST_SIMP_LOCK = threading.Lock()


def decimate_mesh_clean(mesh: trimesh.Trimesh, target_tris: int) -> trimesh.Trimesh:
    """Soude d'abord 100 % des sommets 3D coïncidents (y compris les sommets dupliqués
    par `xatlas` le long des coutures UV !) afin d'obtenir une surface manifold fermée,
    puis décime vers `target_tris` triangles en C++ (`fast_simplification`) sous verrou
    (`Simplify::vertices` / `Simplify::triangles` sont globaux en C++ !)."""
    work = trimesh.Trimesh(
        vertices=np.asarray(mesh.vertices, dtype=np.float64),
        faces=np.asarray(mesh.faces, dtype=np.int64),
        process=True,
    )
    work.merge_vertices(merge_tex=True, merge_norm=True)
    n_cur = len(work.faces)
    if n_cur <= target_tris or target_tris < 16:
        return work
    import fast_simplification
    v_in = np.asarray(work.vertices, dtype=np.float32)
    f_in = np.asarray(work.faces, dtype=np.int32)
    ratio = float(np.clip(1.0 - float(target_tris) / float(n_cur), 0.02, 0.992))
    v_out, f_out = v_in, f_in
    with _FAST_SIMP_LOCK:
        for agg_val in (5, 7, 8, 9, 10):
            v_out, f_out = fast_simplification.simplify(v_in, f_in, target_reduction=ratio, agg=agg_val)
            if len(f_out) <= target_tris * 1.12:
                break
    # v5.2 — garde-fous anti-artefacts : aux ratios extrêmes (LOD2 ~15 %), le
    # décimiteur C++ peut sortir des pointes/slivers hors de la surface d'origine
    # (facettes noires visibles sur la planche QA). On re-clippe les sommets dans
    # le bbox source (un LOD ne doit jamais dépasser son high-poly) et on purge
    # les faces dégénérées, sans rouvrir le maillage.
    v_out = np.clip(np.asarray(v_out, dtype=np.float64),
                    v_in.min(axis=0) - 1e-4, v_in.max(axis=0) + 1e-4)
    out = trimesh.Trimesh(vertices=v_out, faces=f_out, process=True)
    try:
        out.update_faces(out.nondegenerate_faces(height=1e-5))
        out.remove_unreferenced_vertices()
    except Exception:
        pass
    return out


def _bilinear_sample_pil_image(img: Image.Image, uv_pts: np.ndarray, linear_srgb: bool = False) -> np.ndarray:
    """Échantillonne bilinéairement une image PIL aux coordonnées glTF `uv_pts` `(N, 2)` en `[0..1]`."""
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    if linear_srgb:
        # Les textures glTF BaseColor sont encodées sRGB ; le bake interne travaille en sRGB `[0..1]`
        pass
    h, w, _ = arr.shape
    fx = np.clip(uv_pts[:, 0], 0.0, 1.0) * (w - 1)
    fy = np.clip(1.0 - uv_pts[:, 1], 0.0, 1.0) * (h - 1)
    x0 = np.floor(fx).astype(np.int32)
    y0 = np.floor(fy).astype(np.int32)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    tx = (fx - x0)[:, None]
    ty = (fy - y0)[:, None]
    c00 = arr[y0, x0]
    c10 = arr[y0, x1]
    c01 = arr[y1, x0]
    c11 = arr[y1, x1]
    return ((1.0 - ty) * ((1.0 - tx) * c00 + tx * c10) + ty * ((1.0 - tx) * c01 + tx * c11)).astype(np.float32)


def _build_exterior_high_poly_from_union(
    union_mesh: trimesh.Trimesh,
    part_entries: list[tuple[trimesh.Trimesh, mk.Material, str, int]],
) -> tuple[trimesh.Trimesh, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Construit un High-Poly 100 % surfacique externe (zéro face interne enterrée aux
    jonctions CSG !) en étiquetant chaque triangle de `union_mesh` par sa pièce d'origine
    exacte, puis en séparant proprement les frontières de matériaux (zéro bavage d'albédo
    entre cône rouge et fût blanc, yeux et visage, emblèmes et casquette !)."""
    ao_u = pbr.compute_ambient_occlusion(union_mesh).astype(np.float32)
    curv_u = pbr.compute_edge_wear(union_mesh).astype(np.float32)

    all_pts, all_nrm, all_pid = [], [], []
    total_area = sum(max(float(e[0].area), 1e-8) for e in part_entries) + 1e-12
    for pid, (pm, _, _, _) in enumerate(part_entries):
        share = max(float(pm.area), 1e-8) / total_area
        n_s = min(max(int(200_000 * share), len(pm.faces) * 3, 512), 55_000)
        ps, fi = trimesh.sample.sample_surface(pm, n_s, seed=42 + pid)
        fn = pm.face_normals[fi]
        ps = np.vstack([ps, pm.triangles_center])
        fn = np.vstack([fn, pm.face_normals])
        all_pts.append(ps.astype(np.float32))
        all_nrm.append(fn.astype(np.float32))
        all_pid.append(np.full(len(ps), pid, dtype=np.int32))

    src_pts = np.vstack(all_pts)
    src_nrm = np.vstack(all_nrm)
    src_pid = np.concatenate(all_pid)
    tree = cKDTree(src_pts)

    fc = np.asarray(union_mesh.triangles_center, dtype=np.float32)
    fn_u = np.asarray(union_mesh.face_normals, dtype=np.float32)
    dists, idx = tree.query(fc, k=8, workers=-1)
    dots = np.sum(src_nrm[idx] * fn_u[:, None, :], axis=2)
    diag = float(np.linalg.norm(union_mesh.extents)) + 1e-6
    # Départage coplanaire exact (`-1.5e-4 * pid`) en faveur des pièces de détail ajoutées après le corps
    score = dists / diag + 0.11 * (1.0 - np.clip(dots, -0.2, 1.0)) - 1.5e-4 * src_pid[idx]
    face_pid = src_pid[idx[np.arange(len(fc)), np.argmin(score, axis=1)]]

    v_u = np.asarray(union_mesh.vertices, dtype=np.float64)
    f_u = np.asarray(union_mesh.faces, dtype=np.int64)
    sub_meshes, sub_alb, sub_rgh, sub_mtl, sub_mid, sub_ao, sub_crv = [], [], [], [], [], [], []
    for pid in np.unique(face_pid):
        f_sub = f_u[face_pid == pid]
        used_v, inv_f = np.unique(f_sub.reshape(-1), return_inverse=True)
        sm = trimesh.Trimesh(vertices=v_u[used_v], faces=inv_f.reshape(-1, 3), process=False)
        sm.fix_normals(multibody=False)
        _, mat_use, _, mid_val = part_entries[int(pid)]
        nv = len(used_v)
        sub_meshes.append(sm)
        sub_alb.append(np.tile(np.asarray(mat_use.color, dtype=np.float32), (nv, 1)))
        sub_rgh.append(np.full(nv, float(mat_use.roughness), dtype=np.float32))
        sub_mtl.append(np.full(nv, float(mat_use.metallic), dtype=np.float32))
        sub_mid.append(np.full(nv, int(mid_val), dtype=np.int32))
        sub_ao.append(ao_u[used_v])
        sub_crv.append(curv_u[used_v])

    ext_hi = trimesh.util.concatenate(sub_meshes)
    return (
        ext_hi,
        np.vstack(sub_alb),
        np.concatenate(sub_rgh),
        np.concatenate(sub_mtl),
        np.concatenate(sub_mid),
        np.concatenate(sub_ao),
        np.concatenate(sub_crv),
    )


def prepare_high_poly_sampler(
    high_mesh: trimesh.Trimesh,
    high_vertex_albedo: np.ndarray,
    high_vertex_rough: np.ndarray,
    high_vertex_metal: np.ndarray,
    high_vertex_mat_id: np.ndarray | None = None,
    ao_override: np.ndarray | None = None,
    curv_override: np.ndarray | None = None,
) -> dict:
    """Pré-calcule UNE SEULE FOIS l'AO, la Courbure, l'échantillonnage de surface et le
    `cKDTree` multi-cœurs d'un maillage `high_mesh` afin de réutiliser ce cache instantanément
    sur `LOD0`, `Blade`, `Hilt`, etc. sans jamais recalculer 5 fois le High-Poly !"""
    ao_hi = ao_override.astype(np.float32) if ao_override is not None else pbr.compute_ambient_occlusion(high_mesh).astype(np.float32)
    curv_hi = curv_override.astype(np.float32) if curv_override is not None else pbr.compute_edge_wear(high_mesh).astype(np.float32)
    v_hi = np.asarray(high_mesh.vertices, dtype=np.float32)
    n_hi = np.asarray(high_mesh.vertex_normals, dtype=np.float32)
    if high_vertex_mat_id is None:
        v_mid = np.where(high_vertex_metal > 0.72, MAT_BRUSHED_STEEL,
                         np.where(high_vertex_rough > 0.68, MAT_RUBBER_POLY, MAT_CLEAN_ENAMEL)).astype(np.int32)
    else:
        v_mid = np.asarray(high_vertex_mat_id, dtype=np.int32)

    n_surf = min(max(len(high_mesh.faces) * 3, 60_000), 130_000)
    pts_s, face_idx = trimesh.sample.sample_surface(high_mesh, n_surf, seed=42)
    # Ajoute systématiquement tous les centroïdes exacts des triangles High-Poly pour
    # garantir une netteté laser sur les petits détails fins (liserés, pupilles, rivets) !
    all_fi = np.arange(len(high_mesh.faces), dtype=np.int64)
    pts_s = np.vstack([pts_s, high_mesh.triangles_center]).astype(np.float32)
    face_idx = np.concatenate([face_idx, all_fi])
    f_hi = np.asarray(high_mesh.faces, dtype=np.int64)[face_idx]
    va, vb, vc = v_hi[f_hi[:, 0]], v_hi[f_hi[:, 1]], v_hi[f_hi[:, 2]]
    e0, e1, vp = vb - va, vc - va, pts_s - va
    d00 = np.sum(e0 * e0, axis=1)
    d01 = np.sum(e0 * e1, axis=1)
    d11 = np.sum(e1 * e1, axis=1)
    d20 = np.sum(vp * e0, axis=1)
    d21 = np.sum(vp * e1, axis=1)
    inv_d = 1.0 / np.maximum(d00 * d11 - d01 * d01, 1e-18)
    bw1 = np.clip((d11 * d20 - d01 * d21) * inv_d, 0.0, 1.0)
    bw2 = np.clip((d00 * d21 - d01 * d20) * inv_d, 0.0, 1.0)
    bw0 = np.clip(1.0 - bw1 - bw2, 0.0, 1.0)
    bsum = bw0 + bw1 + bw2 + 1e-12
    bw0, bw1, bw2 = (bw0 / bsum).astype(np.float32), (bw1 / bsum).astype(np.float32), (bw2 / bsum).astype(np.float32)

    ia_h, ib_h, ic_h = f_hi[:, 0], f_hi[:, 1], f_hi[:, 2]
    nrm_s = bw0[:, None] * n_hi[ia_h] + bw1[:, None] * n_hi[ib_h] + bw2[:, None] * n_hi[ic_h]
    nrm_s /= np.linalg.norm(nrm_s, axis=1, keepdims=True) + 1e-12

    alb_s = bw0[:, None] * high_vertex_albedo[ia_h] + bw1[:, None] * high_vertex_albedo[ib_h] + bw2[:, None] * high_vertex_albedo[ic_h]
    rgh_s = bw0 * high_vertex_rough[ia_h] + bw1 * high_vertex_rough[ib_h] + bw2 * high_vertex_rough[ic_h]
    mtl_s = bw0 * high_vertex_metal[ia_h] + bw1 * high_vertex_metal[ib_h] + bw2 * high_vertex_metal[ic_h]

    # Échantillonnage bilinéaire pleine résolution 1024²/2048² si `high_mesh` possède un atlas UV !
    vis = getattr(high_mesh, "visual", None)
    uv_hi = getattr(vis, "uv", None)
    mat_hi = getattr(vis, "material", None)
    if uv_hi is not None and len(uv_hi) == len(v_hi) and mat_hi is not None:
        uv_arr = np.asarray(uv_hi, dtype=np.float32)
        uv_s = bw0[:, None] * uv_arr[ia_h] + bw1[:, None] * uv_arr[ib_h] + bw2[:, None] * uv_arr[ic_h]
        bc_tex = getattr(mat_hi, "baseColorTexture", None)
        mr_tex = getattr(mat_hi, "metallicRoughnessTexture", None)
        if bc_tex is not None:
            alb_s = _bilinear_sample_pil_image(bc_tex, uv_s)
        if mr_tex is not None:
            mr_s = _bilinear_sample_pil_image(mr_tex, uv_s)
            rgh_s = mr_s[:, 1]
            mtl_s = mr_s[:, 2]

    return {
        "nrm_s": nrm_s,
        "alb_s": alb_s,
        "rgh_s": rgh_s,
        "mtl_s": mtl_s,
        "ao_s": bw0 * ao_hi[ia_h] + bw1 * ao_hi[ib_h] + bw2 * ao_hi[ic_h],
        "crv_s": bw0 * curv_hi[ia_h] + bw1 * curv_hi[ib_h] + bw2 * curv_hi[ic_h],
        "mid_s": v_mid[ia_h],
        "kdtree": cKDTree(pts_s),
        "diag": float(np.linalg.norm(high_mesh.extents)) + 1e-6,
        "bounds": high_mesh.bounds,
    }


def build_shared_atlas_lod(lod0_mesh: trimesh.Trimesh, baked_lod0: dict, low_raw: trimesh.Trimesh, mip_size: int, use_normal: bool = True) -> trimesh.Trimesh:
    """Construit `LOD1` ou `LOD2` en transférant instantanément (`< 0.05 s`, zéro `xatlas`)
    les coordonnées UV exactes du `LOD0` par voisinage surface+normale + mipmap dédiée !"""
    v0 = np.asarray(lod0_mesh.vertices, dtype=np.float32)
    n0 = np.asarray(lod0_mesh.vertex_normals, dtype=np.float32)
    uv0 = np.asarray(lod0_mesh.visual.uv, dtype=np.float64)
    tree0 = cKDTree(v0)

    vl = np.asarray(low_raw.vertices, dtype=np.float32)
    nl = np.asarray(low_raw.vertex_normals, dtype=np.float32)
    dists, idx_k = tree0.query(vl, k=min(8, len(v0)), workers=-1)
    if idx_k.ndim == 1:
        best_v = idx_k
    else:
        al = np.sum(n0[idx_k] * nl[:, None, :], axis=2)
        sc = dists / (float(np.linalg.norm(lod0_mesh.extents)) + 1e-6) + 0.02 * (1.0 - np.clip(al, -0.2, 1.0))
        best_v = idx_k[np.arange(len(vl)), np.argmin(sc, axis=1)]

    uv_lod = uv0[best_v]
    alb_m = baked_lod0["albedo"].resize((mip_size, mip_size), Image.Resampling.BILINEAR)
    orm_m = baked_lod0["orm"].resize((mip_size, mip_size), Image.Resampling.BILINEAR)
    out_m = low_raw.copy()
    # `use_normal=False` (LOD2) : une normale tangente bakée pour la surface LOD0
    # produit des artefacts d'ombrage sur un maillage décimé à 15 % — le LOD
    # lointain garde un PBR plat (albédo + ORM), sans carte de normales.
    nrm_m = baked_lod0["normal_gl"].resize((mip_size, mip_size), Image.Resampling.BILINEAR) if use_normal else None
    pbr_m = trimesh.visual.material.PBRMaterial(
        name="game_lod_pbr",
        baseColorFactor=[255, 255, 255, 255],
        baseColorTexture=alb_m,
        metallicRoughnessTexture=orm_m,
        occlusionTexture=orm_m,
        normalTexture=nrm_m,
        metallicFactor=1.0,
        roughnessFactor=1.0,
    )
    out_m.visual = trimesh.visual.TextureVisuals(uv=uv_lod, material=pbr_m)
    out_m.metadata = dict(getattr(out_m, "metadata", {}) or {})
    out_m.metadata["mikk_tangents"] = mk.compute_mikk_tangents(out_m, uv_lod)
    return out_m


def bake_high_to_low(
    high_mesh: trimesh.Trimesh,
    high_vertex_albedo: np.ndarray,
    high_vertex_rough: np.ndarray,
    high_vertex_metal: np.ndarray,
    low_mesh_in: trimesh.Trimesh,
    high_vertex_mat_id: np.ndarray | None = None,
    ai_views: dict[str, str | Path] | None = None,
    hp_cache: dict | None = None,
    tex_size: int = 1024,
    weathering: bool = True,
    dirt_amount: float = 0.36,
    grime_amount: float = 0.22,
    delight_pass: bool = False,
    decal_strength: float = 0.65,
    glass_only: bool = False,
    glass_tint=None,
) -> dict:
    """Cuit par projection géométrique 3D exacte un maillage `high_mesh` arbitrairement dense
    (`50k - 150k tris`) vers un maillage temps réel `low_mesh_in` (`1k - 6k tris`)."""
    S = int(tex_size)
    v_labels = np.zeros(len(low_mesh_in.vertices), dtype=np.int64)
    low_uv_mesh, _, uv = pbr.unwrap(low_mesh_in, v_labels)
    tangents_v4 = mk.compute_mikk_tangents(low_uv_mesh, uv)

    sampler = hp_cache or prepare_high_poly_sampler(
        high_mesh, high_vertex_albedo, high_vertex_rough, high_vertex_metal, high_vertex_mat_id,
    )
    nrm_s = sampler["nrm_s"]
    alb_s = sampler["alb_s"]
    rgh_s = sampler["rgh_s"]
    mtl_s = sampler["mtl_s"]
    ao_s  = sampler["ao_s"]
    crv_s = sampler["crv_s"]
    mid_s = sampler["mid_s"]
    kdtree = sampler["kdtree"]

    # Rastérisation vectorisée de l'atlas UV `S × S` du Low-Poly
    f_low = np.asarray(low_uv_mesh.faces, dtype=np.int64)
    v_low = np.asarray(low_uv_mesh.vertices, dtype=np.float32)
    n_low = np.asarray(low_uv_mesh.vertex_normals, dtype=np.float32)
    tri_uv = np.empty((len(f_low), 3, 2), dtype=np.float64)
    tri_uv[..., 0] = uv[f_low, 0] * S
    tri_uv[..., 1] = (1.0 - uv[f_low, 1]) * S

    rast = pbr.rasterize_uv_triangles(tri_uv, S)
    f_hit, xs, ys, w0, w1, w2 = rast
    la, lb, lc = f_low[f_hit, 0], f_low[f_hit, 1], f_low[f_hit, 2]
    w0f, w1f, w2f = w0.astype(np.float32), w1.astype(np.float32), w2.astype(np.float32)

    pos_px = w0f[:, None] * v_low[la] + w1f[:, None] * v_low[lb] + w2f[:, None] * v_low[lc]
    N_px = w0f[:, None] * n_low[la] + w1f[:, None] * n_low[lb] + w2f[:, None] * n_low[lc]
    N_px /= np.linalg.norm(N_px, axis=1, keepdims=True) + 1e-12
    T4_px = w0f[:, None] * tangents_v4[la] + w1f[:, None] * tangents_v4[lb] + w2f[:, None] * tangents_v4[lc]
    T_px = T4_px[:, :3] - N_px * np.sum(N_px * T4_px[:, :3], axis=1, keepdims=True)
    T_px /= np.linalg.norm(T_px, axis=1, keepdims=True) + 1e-12
    sign_w = np.where(T4_px[:, 3:4] < 0.0, -1.0, 1.0).astype(np.float32)
    B_px = np.cross(N_px, T_px) * sign_w

    # Projection Cage Ray-Aware multi-cœurs (`workers=-1`)
    dists, idx_k = kdtree.query(pos_px, k=6, workers=-1)
    cand_n = nrm_s[idx_k]
    align = np.sum(cand_n * N_px[:, None, :], axis=2)
    # v5.7 — le poids de la normale passe de 0.035 à 0.09. Quand deux surfaces
    # du high-poly sont COINCIDENTES (disque de base du cône et capuchon du fût,
    # tous deux à la jonction), la distance est nulle pour les deux et seule la
    # normale doit arbitrer : sans ça le disque intérieur (normale opposée)
    # gagnait et le blanc du fût bavait en créneaux sur le cône rouge.
    score = dists / sampler["diag"] + 0.09 * (1.0 - np.clip(align, -0.2, 1.0))
    best = idx_k[np.arange(len(pos_px)), np.argmin(score, axis=1)]

    nhi_px = nrm_s[best]
    col_px = alb_s[best]
    rgh_px = rgh_s[best]
    mtl_px = mtl_s[best]
    ao_px = ao_s[best]
    crv_px = crv_s[best]
    mid_px = mid_s[best]

    delight_meta = {}
    if delight_pass:
        col_px, delight_meta = dl.delight_albedo_3d(col_px, nhi_px, strength=0.78)

    ai_hgt = np.zeros(len(pos_px), dtype=np.float32)
    if ai_views:
        import gpu_bridge as gb
        # 1) Micro-texture 360° sans couture depuis tuiles GPU Datacenter (`tile_*.png`) si présentes :
        #    garantit 0 zone plastique même sous le menton, sous le nez, sur les 20 dents et au dos !
        ai_folder = Path(next(iter(ai_views.values()))).parent
        tile_lac_p = ai_folder / "tile_urushi_crimson.png"
        tile_gld_p = ai_folder / "tile_gilded_teeth.png"
        tile_brd_p = ai_folder / "tile_carved_beard.png"
        is_dark_cav = col_px.max(axis=1) < 0.085
        is_metallic = mtl_px > 0.50
        # Détecte poils/barbe sculptés clairs (ivoire / argent) pour leur appliquer leur propre tuile GPU
        is_hair_ivory = (~is_metallic) & (col_px.min(axis=1) > 0.52)
        p_unit = (pos_px - high_mesh.bounds[0]) / max(float(np.linalg.norm(high_mesh.bounds[1] - high_mesh.bounds[0])), 1e-5)

        if tile_lac_p.is_file():
            t_lac = gb._load_tile(str(tile_lac_p))
            s_lac = gb._triplanar_sample_tile(t_lac, p_unit, nhi_px, scale=3.2).astype(np.float32)
            lac_mean = np.clip(s_lac.mean(axis=0, keepdims=True), 0.08, None)
            lac_mod = np.clip(0.38 + 0.62 * (s_lac / lac_mean), 0.25, 1.55)
            non_metal = (~is_metallic) & (~is_dark_cav) & (~is_hair_ivory)
            col_px[non_metal] = np.clip(col_px[non_metal] * lac_mod[non_metal], 0.0, 1.0)
            lac_lum = s_lac @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
            ai_hgt += np.where(non_metal, (lac_lum - float(lac_lum.mean())) * 0.55, 0.0)
            rgh_px = np.where(non_metal, np.clip(rgh_px + (float(lac_lum.mean()) - lac_lum) * 0.30, 0.08, 0.90), rgh_px)

        if tile_brd_p.is_file() and np.any(is_hair_ivory):
            t_brd = gb._load_tile(str(tile_brd_p))
            s_brd = gb._triplanar_sample_tile(t_brd, p_unit[is_hair_ivory], nhi_px[is_hair_ivory], scale=4.2).astype(np.float32)
            brd_mean = np.clip(s_brd.mean(axis=0, keepdims=True), 0.12, None)
            col_px[is_hair_ivory] = np.clip(col_px[is_hair_ivory] * (0.35 + 0.65 * (s_brd / brd_mean)), 0.0, 0.90)
            brd_lum = s_brd @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
            ai_hgt[is_hair_ivory] += (brd_lum - float(brd_lum.mean())) * 0.85
            rgh_px[is_hair_ivory] = np.clip(rgh_px[is_hair_ivory] + (float(brd_lum.mean()) - brd_lum) * 0.25, 0.28, 0.88)

        if tile_gld_p.is_file() and np.any(is_metallic):
            t_gld = gb._load_tile(str(tile_gld_p))
            s_gld = gb._triplanar_sample_tile(t_gld, p_unit[is_metallic], nhi_px[is_metallic], scale=5.5).astype(np.float32)
            gld_mean = np.clip(s_gld.mean(axis=0, keepdims=True), 0.10, None)
            col_px[is_metallic] = np.clip(col_px[is_metallic] * (0.45 + 0.55 * (s_gld / gld_mean)), 0.0, 1.0)
            gld_lum = s_gld @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
            ai_hgt[is_metallic] += (gld_lum - float(gld_lum.mean())) * 0.45
            rgh_px[is_metallic] = np.clip(rgh_px[is_metallic] + (float(gld_lum.mean()) - gld_lum) * 0.24, 0.10, 0.65)

        # 2) Projection Z-buffer multi-vues GPU Datacenter : 0 % sur les métaux dorés & cavités noires
        #    (élimine à 100 % tout double reflet/pupille fantôme sur les yeux et les 20 dents !)
        ai_col, ai_ortho_hgt, ai_cov = gb.sample_orthographic_ai_views_zbuffer(
            high_mesh, pos_px, nhi_px, {k: str(v) for k, v in ai_views.items()},
        )
        ai_hgt = ai_hgt + np.where(is_metallic | is_dark_cav, 0.0, ai_ortho_hgt)
        ai_blend = np.where(
            is_dark_cav | is_metallic | (mid_px == MAT_BRUSHED_STEEL),
            0.0,
            ai_cov * np.where(is_hair_ivory, 0.55, 0.88),
        )
        col_px = col_px * (1.0 - ai_blend[:, None]) + ai_col * ai_blend[:, None]
        rgh_px = np.clip(rgh_px * (1.0 - 0.28 * ai_ortho_hgt * ai_cov), 0.06, 0.95)

    if weathering:
        w_amt = 0.0 if (delight_pass or ai_views) else 0.42
        # v5.8 — les doses ne sont plus figées : `dirt_amount` / `grime_amount`
        # sont exposés par `export_game_package`. Un objet de studio (arme,
        # figurine) ne se salit pas comme une caisse de chantier, et une AO
        # calculée sur une union CSG produit de GROSSES taches molles : à
        # dirt 0.30 elles lisaient comme un camouflage sur le garde-main du G36.
        _d = float(np.clip(dirt_amount, 0.0, 1.0))
        _g = float(np.clip(grime_amount, 0.0, 1.0))
        d_amt = 0.04 if ai_views else (0.14 * _d / 0.36 if delight_pass else _d)
        g_amt = 0.05 if ai_views else (0.08 * _g / 0.22 if delight_pass else _g)
        dec_amt = 0.0 if ai_views else (0.06 if delight_pass else decal_strength)
        col_px, rgh_px, mtl_px, ao_px, hgt_px = apply_game_weathering(
            col_px, rgh_px, mtl_px, ao_px, crv_px,
            pos_px, nhi_px, high_mesh.bounds,
            mat_id=mid_px,
            wear_amount=w_amt, dirt_amount=d_amt, grime_amount=g_amt,
            decal_strength=dec_amt,
        )
        hgt_px = hgt_px + ai_hgt * 1.35
    else:
        col_px = compress_albedo_headroom(col_px)
        lum_det = col_px @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        hgt_px = (ai_hgt * 0.45 + 0.14 * (lum_det - float(np.median(lum_det)))).astype(np.float32)

    # Transformation de la normale High-Poly dans l'Espace Tangent Mikk du Low-Poly !
    ts_x = np.sum(nhi_px * T_px, axis=1)
    ts_y = np.sum(nhi_px * B_px, axis=1)
    ts_z = np.maximum(np.sum(nhi_px * N_px, axis=1), 0.12)

    albedo_map = np.zeros((S, S, 3), dtype=np.float32)
    orm_map = np.zeros((S, S, 3), dtype=np.float32)
    orm_map[..., 0], orm_map[..., 1] = 1.0, 0.5
    ts_map = np.zeros((S, S, 3), dtype=np.float32)
    ts_map[..., 2] = 1.0
    h_map = np.zeros((S, S), dtype=np.float32)
    mask_uv = np.zeros((S, S), dtype=bool)

    albedo_map[ys, xs] = col_px
    orm_map[ys, xs, 0] = ao_px
    orm_map[ys, xs, 1] = rgh_px
    orm_map[ys, xs, 2] = mtl_px
    ts_map[ys, xs, 0] = ts_x
    ts_map[ys, xs, 1] = ts_y
    ts_map[ys, xs, 2] = ts_z
    h_map[ys, xs] = hgt_px
    mask_uv[ys, xs] = True

    _, nn_i = ndimage.distance_transform_edt(~mask_uv, return_indices=True)
    albedo_map = albedo_map[nn_i[0], nn_i[1]]
    orm_map = orm_map[nn_i[0], nn_i[1]]
    ts_map = ts_map[nn_i[0], nn_i[1]]
    h_map = h_map[nn_i[0], nn_i[1]]

    # Combine la normale géométrique High->Low avec le micro-relief Normal Stamps / grain !
    dy_h, dx_h = np.gradient(h_map * 1.45)
    nx_gl = ts_map[..., 0] - dx_h
    ny_gl = ts_map[..., 1] + dy_h
    nz_gl = ts_map[..., 2]
    n_norm = np.sqrt(nx_gl * nx_gl + ny_gl * ny_gl + nz_gl * nz_gl) + 1e-12
    nx_gl, ny_gl, nz_gl = nx_gl / n_norm, ny_gl / n_norm, nz_gl / n_norm

    normal_gl_u8 = (np.stack([nx_gl, ny_gl, nz_gl], axis=-1) * 0.5 + 0.5) * 255.0
    # Convention Unreal Engine DirectX (`-Y` : canal Vert inversé `1.0 - G` !)
    normal_dx_u8 = (np.stack([nx_gl, -ny_gl, nz_gl], axis=-1) * 0.5 + 0.5) * 255.0

    alb_img = pbr.compress_png(Image.fromarray(np.clip(albedo_map * 255.0, 0, 255).astype(np.uint8), "RGB"))
    orm_img = pbr.compress_png(Image.fromarray(np.clip(orm_map * 255.0, 0, 255).astype(np.uint8), "RGB"))
    nrm_gl_img = pbr.compress_png(Image.fromarray(np.clip(normal_gl_u8, 0, 255).astype(np.uint8), "RGB"))
    nrm_dx_img = pbr.compress_png(Image.fromarray(np.clip(normal_dx_u8, 0, 255).astype(np.uint8), "RGB"))

    # Unity HDRP MaskMap : R = Metallic, G = Ambient Occlusion, B = Detail Mask (255), A = Smoothness (1 - Roughness)
    mask_map_u8 = np.stack([
        orm_map[..., 2] * 255.0,
        orm_map[..., 0] * 255.0,
        np.full((S, S), 255.0, dtype=np.float32),
        (1.0 - orm_map[..., 1]) * 255.0,
    ], axis=-1)
    unity_mask_img = pbr.compress_png(Image.fromarray(np.clip(mask_map_u8, 0, 255).astype(np.uint8), "RGBA"))

    mat_pbr = trimesh.visual.material.PBRMaterial(
        name="SM_GamePBR",
        baseColorFactor=[255, 255, 255, 255],
        baseColorTexture=alb_img,
        metallicRoughnessTexture=orm_img,
        occlusionTexture=orm_img,
        normalTexture=nrm_gl_img,
        metallicFactor=1.0,
        roughnessFactor=1.0,
    )
    if glass_only:
        # Asset 100 % verre (verre à vin) : on garde l'atlas PBR mais on restitue
        # la transparence du matériau d'origine, sinon le verre se lit comme une
        # céramique blanche opaque.
        op = float(np.clip(glass_tint[3] if len(glass_tint) > 3 else 0.24, 0.10, 0.85))
        mat_pbr.baseColorFactor = [int(v * 255) for v in glass_tint[:3]] + [int(op * 255)]
        mat_pbr.alphaMode = "BLEND"
        mat_pbr.metallicFactor = 0.0
        mat_pbr.roughnessFactor = 0.08
    low_uv_mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=mat_pbr)

    return {
        "mesh_lod0": low_uv_mesh,
        "uv": uv,
        "tangents": tangents_v4,
        "albedo": alb_img,
        "orm": orm_img,
        "normal_gl": nrm_gl_img,
        "normal_dx": nrm_dx_img,
        "unity_mask": unity_mask_img,
        "delight_metrics": delight_meta,
    }


def transfer_uv_to_lod(lod0_uv_mesh: trimesh.Trimesh, decimated_mesh: trimesh.Trimesh,
                       mat_pbr: trimesh.visual.material.PBRMaterial) -> trimesh.Trimesh:
    """Transfère les coordonnées UV de `lod0_uv_mesh` vers `LOD1` / `LOD2` par projection
    K-NN par sommet pour que TOUS les niveaux de LOD partagent le MÊME atlas de textures !"""
    tree = cKDTree(np.asarray(lod0_uv_mesh.vertices, dtype=np.float32))
    _, idx = tree.query(np.asarray(decimated_mesh.vertices, dtype=np.float32), k=1)
    uv_lod0 = np.asarray(lod0_uv_mesh.visual.uv, dtype=np.float32)
    m_out = decimated_mesh.copy()
    m_out.visual = trimesh.visual.TextureVisuals(uv=uv_lod0[idx], material=mat_pbr)
    return m_out


# --------------------------------------------------------------------------- #
# 5. Collisions Convexes `UCX_*` / `-colonly` & Inférence de `SOCKET_*` Gameplay
# --------------------------------------------------------------------------- #

def generate_convex_colliders(
    source_meshes: list[trimesh.Trimesh],
    max_hulls: int = 6,
    max_tris_per_hull: int = 64,
) -> list[trimesh.Trimesh]:
    """Décompose un objet en `<= max_hulls` coques convexes propres (`<= max_tris_per_hull` tris)
    préservant les ouvertures (sous une table, embrasure de porte, passages de roues, garde d'épée)."""
    candidates = [m for m in source_meshes if len(m.vertices) >= 4 and m.volume >= 0]
    if not candidates:
        return []

    if len(candidates) <= max_hulls:
        groups = [[m] for m in candidates]
    else:
        # Regroupe les pièces par K-means spatial rapide sur leurs centres de gravité !
        centers = np.array([0.5 * (m.bounds[0] + m.bounds[1]) for m in candidates], dtype=np.float64)
        rng = np.random.default_rng(42)
        pivots = centers[rng.choice(len(centers), size=max_hulls, replace=False)].copy()
        assign = np.zeros(len(centers), dtype=np.int32)
        for _ in range(12):
            d2 = np.linalg.norm(centers[:, None, :] - pivots[None, :, :], axis=2)
            assign = np.argmin(d2, axis=1)
            for k in range(max_hulls):
                sel = centers[assign == k]
                if len(sel) > 0:
                    pivots[k] = sel.mean(axis=0)
        groups = [[candidates[i] for i in range(len(candidates)) if assign[i] == k]
                  for k in range(max_hulls)]
        groups = [g for g in groups if g]

    hulls = []
    for grp in groups:
        pts = np.vstack([m.vertices for m in grp])
        if len(pts) < 4:
            continue
        hull = trimesh.convex.convex_hull(pts)
        if len(hull.faces) > max_tris_per_hull:
            # v5.3 — garantie dure du budget + englobement au millimètre.
            # `fast_simplification` ne converge pas sur une coque convexe (résidu
            # mesuré : 108 faces pour une cible de 28), et gonfler les plans d'un
            # polytope explose la triangulation (facettes polygonales). La seule
            # garantie simple est SIMPLICIALE : un hull de V points génériques a
            # au plus 2V-4 triangles, donc V = (max_tris+4)//2 points suffisent.
            #  1) farthest-point sampling sélectionne V sommets extrêmes sources ;
            #  2) raffinement glouton : tant qu'un point source viole le hull, on
            #     remplace le point sélectionné dont l'échange réduit le plus la
            #     violation maximale. Budget invariant (toujours V points),
            #     englobement convergé (<= 1 mm) en quelques itérations.
            max_v = max(4, (max_tris_per_hull + 4) // 2)
            if len(pts) > max_v:
                sel = [0]
                dmin = np.linalg.norm(pts - pts[0], axis=1)
                while len(sel) < max_v:
                    i = int(np.argmax(dmin))
                    sel.append(i)
                    dmin = np.minimum(dmin, np.linalg.norm(pts - pts[i], axis=1))

                from scipy.spatial import ConvexHull

                def _worst_excess(idx: list[int]):
                    # scipy brut : pas de construction de Trimesh ni de fix_normals
                    # (cf. profil : trimesh.convex_hull = 2× plus lent).
                    eq = ConvexHull(pts[idx]).equations  # n·x + off <= 0 à l'intérieur
                    ex = (pts @ eq[:, :3].T + eq[:, 3]).max(axis=1)
                    return float(ex.max()), int(np.argmax(ex))

                viol, p_star = _worst_excess(sel)
                for _ in range(12):
                    if viol <= 1e-3:
                        break
                    best = None
                    for r in range(len(sel)):
                        if sel[r] == p_star:
                            continue
                        trial = list(sel)
                        trial[r] = p_star
                        v, _ = _worst_excess(trial)
                        if best is None or v < best[1]:
                            best = (trial, v)
                    if best is None or best[1] >= viol:
                        break  # aucun progrès possible
                    sel, viol = best[0], best[1]
                    _, p_star = _worst_excess(sel)
                hull = trimesh.convex.convex_hull(pts[sel])
        hulls.append(hull)
    return hulls


def infer_gameplay_sockets(
    name: str,
    bounds: np.ndarray,
    joints: dict | None = None,
    declared: dict | None = None,
) -> dict:
    """Complète les `SOCKET_*` déclarés par des sockets gameplay intelligents adaptés au type d'asset."""
    out = dict(declared or {})
    bmin, bmax = bounds[0], bounds[1]
    c = 0.5 * (bmin + bmax)
    lname = name.lower()

    out.setdefault("SOCKET_origin_ground", {"position": [float(c[0]), float(c[1]), float(bmin[2])], "rotation_deg": [0, 0, 0]})
    out.setdefault("SOCKET_top", {"position": [float(c[0]), float(c[1]), float(bmax[2])], "rotation_deg": [0, 0, 0]})

    if any(w in lname for w in ("sword", "katana", "epee", "blade", "axe", "hammer")):
        grip_z = float(bmin[2] + 0.14 * (bmax[2] - bmin[2]))
        out.setdefault("SOCKET_grip", {"position": [float(c[0]), float(c[1]), grip_z], "rotation_deg": [0, 0, 0]})
        out.setdefault("SOCKET_tip", {"position": [float(c[0]), float(c[1]), float(bmax[2])], "rotation_deg": [0, 0, 0]})
        out.setdefault("SOCKET_trail_mid", {"position": [float(c[0]), float(c[1]), float(0.5 * (grip_z + bmax[2]))], "rotation_deg": [0, 0, 0]})
    elif any(w in lname for w in ("car", "moto", "vehicle", "truck")):
        out.setdefault("SOCKET_headlight_front", {"position": [float(bmax[0]), float(c[1]), float(bmin[2] + 0.45 * (bmax[2] - bmin[2]))], "rotation_deg": [0, 0, 0]})
        out.setdefault("SOCKET_exhaust", {"position": [float(bmin[0]), float(c[1]), float(bmin[2] + 0.25 * (bmax[2] - bmin[2]))], "rotation_deg": [0, 0, 180]})
        out.setdefault("SOCKET_driver_seat", {"position": [float(c[0]), float(c[1]), float(bmin[2] + 0.62 * (bmax[2] - bmin[2]))], "rotation_deg": [0, 0, 0]})
    else:
        out.setdefault("SOCKET_interact", {"position": [float(c[0]), float(bmin[1]), float(c[2])], "rotation_deg": [0, 0, 0]})

    for jname, jinfo in (joints or {}).items():
        out.setdefault(f"SOCKET_{jname}", {"position": list(jinfo["pivot"]), "rotation_deg": [0, 0, 0]})
    return out


ROBLOX_METERS_PER_STUD = 0.28
ROBLOX_STUDS_PER_METER = 1.0 / ROBLOX_METERS_PER_STUD  # 3.57142857 studs / mètre
ROBLOX_MAX_TRIS_PER_PART = 9_800  # Limite stricte Roblox Studio (< 10 000 tris / MeshPart !)
ROBLOX_MAX_TEX_SIZE = 1024        # Résolution maximale native Roblox `SurfaceAppearance`


def _generate_roblox_luau_script(
    clean_name: str,
    size_studs: list[float],
    sockets_studs: dict[str, list[float]],
    neon_parts: list[dict],
    joints_studs: dict[str, dict],
) -> str:
    """Génère un script Luau prêt à coller dans la Command Bar ou un ServerScript de
    **Roblox Studio** après import de `<Name>_roblox.glb` :
      1. Active `Material = Enum.Material.Neon` + couleur RGB exacte sur chaque pièce `Neon_*`,
      2. Configure `CollisionFidelity` optimal & `CastShadow = true`,
      3. Crée des instances `Attachment` exactes (`GripAttachment`, `TipAttachment`, etc.),
      4. Monte automatiquement un `HingeConstraint` + `ProximityPrompt [E]` sur les couvercles/portes articulés,
      5. Fournit `ConvertToTool(model)` en 1 clic pour les armes (`katana`, `sword`, etc.) avec `Trail` !
    """
    is_weapon = any(k in clean_name.lower() for k in ("sword", "katana", "axe", "blade", "dagger", "spear", "hammer", "shield"))
    lines = [
        f"-- Auto-generated by 3d-forge v5 for ROBLOX STUDIO — Asset: {clean_name}",
        f"-- Dimensions calibrées R15/Rthro (1 Stud = 0.28m) : {size_studs[0]:.2f} x {size_studs[1]:.2f} x {size_studs[2]:.2f} Studs",
        "-- Utilisation : sélectionnez le Model importé dans Workspace puis collez ce script dans la Command Bar Roblox Studio !",
        "",
        "local Selection = game:GetService('Selection')",
        f"local model = Selection:Get()[1] or workspace:FindFirstChild('{clean_name}_roblox') or workspace:FindFirstChild('{clean_name}')",
        "assert(model, '[3d-forge] Sélectionnez le Model importé dans Workspace avant de lancer ce script !')",
        "",
        "-- 1. Configuration PBR MeshParts + Pièces lumineuses Enum.Material.Neon",
        "local NEON_COLORS = {",
    ]
    for np_info in neon_parts:
        r, g, b = np_info["rgb255"]
        lines.append(f"    ['{np_info['name']}'] = Color3.fromRGB({r}, {g}, {b}),")
    lines += [
        "}",
        "",
        "local rootPart = nil",
        "for _, desc in ipairs(model:GetDescendants()) do",
        "    if desc:IsA('MeshPart') then",
        "        desc.CastShadow = true",
        "        if NEON_COLORS[desc.Name] then",
        "            desc.Material = Enum.Material.Neon",
        "            desc.Color = NEON_COLORS[desc.Name]",
        "            local sa = desc:FindFirstChildOfClass('SurfaceAppearance')",
        "            if sa then sa:Destroy() end",
        "        elseif not rootPart or desc.Name:find('Body') then",
        "            rootPart = desc",
        "        end",
        "    end",
        "end",
        "if model:IsA('Model') and rootPart then",
        "    model.PrimaryPart = rootPart",
        "end",
        "",
        "-- 2. Points d'attache Gameplay (Attachments compatibles RaycastHitbox / Trails / VFX)",
        "local SOCKETS_WORLD_OFFSET = {",
    ]
    for sname, sp in sockets_studs.items():
        # Conversion Z-up (3d-forge) -> Y-up (Roblox Studio : X=X, Y=Z, Z=-Y)
        rx, ry, rz = sp[0], sp[2], -sp[1]
        att_name = sname.replace("SOCKET_", "") + "Attachment"
        lines.append(f"    ['{att_name}'] = Vector3.new({rx:.4f}, {ry:.4f}, {rz:.4f}),")
    lines += [
        "}",
        "if rootPart then",
        "    local originCF = model:GetPivot()",
        "    for attName, worldOff in pairs(SOCKETS_WORLD_OFFSET) do",
        "        local att = rootPart:FindFirstChild(attName) or Instance.new('Attachment')",
        "        att.Name = attName",
        "        att.WorldPosition = originCF.Position + worldOff",
        "        att.Parent = rootPart",
        "    end",
        "end",
    ]
    if joints_studs:
        lines += [
            "",
            "-- 3. Articulations physiques automatiques (HingeConstraint Servo + ProximityPrompt [E])",
        ]
        for jname, jinfo in joints_studs.items():
            px, py, pz = jinfo["pivot_studs"][0], jinfo["pivot_studs"][2], -jinfo["pivot_studs"][1]
            ax, ay, az = jinfo["axis"][0], jinfo["axis"][2], -jinfo["axis"][1]
            lines += [
                f"do",
                f"    local moving = model:FindFirstChild('{jname}_mesh', true) or model:FindFirstChild('{jname}', true)",
                f"    if rootPart and moving and moving:IsA('BasePart') then",
                f"        rootPart.Anchored = true",
                f"        moving.Anchored = false",
                f"        local pivotWorld = model:GetPivot().Position + Vector3.new({px:.4f}, {py:.4f}, {pz:.4f})",
                f"        local axisWorld = Vector3.new({ax:.4f}, {ay:.4f}, {az:.4f}).Unit",
                f"        local a0 = Instance.new('Attachment', rootPart)",
                f"        a0.Name = '{jname}_HingeA0'; a0.WorldPosition = pivotWorld; a0.WorldAxis = axisWorld",
                f"        local a1 = Instance.new('Attachment', moving)",
                f"        a1.Name = '{jname}_HingeA1'; a1.WorldPosition = pivotWorld; a1.WorldAxis = axisWorld",
                f"        local hinge = Instance.new('HingeConstraint', rootPart)",
                f"        hinge.Attachment0 = a0; hinge.Attachment1 = a1",
                f"        hinge.ActuatorType = Enum.ActuatorType.Servo",
                f"        hinge.AngularSpeed = 2.6; hinge.ServoMaxTorque = 1e6",
                f"        hinge.LimitsEnabled = true; hinge.LowerAngle = 0; hinge.UpperAngle = 72",
                f"        hinge.TargetAngle = 0",
                f"        local prompt = rootPart:FindFirstChildOfClass('ProximityPrompt') or Instance.new('ProximityPrompt', rootPart)",
                f"        prompt.ActionText = 'Ouvrir / Fermer'; prompt.ObjectText = '{clean_name}'",
                f"        local opened = false",
                f"        prompt.Triggered:Connect(function()",
                f"            opened = not opened",
                f"            hinge.TargetAngle = opened and 68 or 0",
                f"        end)",
                f"    end",
                f"end",
            ]
    if is_weapon:
        lines += [
            "",
            "-- 4. Conversion 1-clic en Tool Roblox jouable (Handle soudé + Trail d'attaque)",
            "local function ConvertToTool(srcModel)",
            f"    local tool = Instance.new('Tool')",
            f"    tool.Name = '{clean_name}'",
            "    tool.RequiresHandle = true",
            "    local handle = Instance.new('Part')",
            "    handle.Name = 'Handle'; handle.Size = Vector3.new(0.4, 0.8, 0.4)",
            "    handle.Transparency = 1; handle.CanCollide = false; handle.Massless = true",
            "    local gripAtt = rootPart and rootPart:FindFirstChild('gripAttachment')",
            "    handle.CFrame = gripAtt and CFrame.new(gripAtt.WorldPosition) or srcModel:GetPivot()",
            "    handle.Parent = tool",
            "    for _, part in ipairs(srcModel:GetDescendants()) do",
            "        if part:IsA('BasePart') then",
            "            local c = part:Clone()",
            "            c.Anchored = false; c.CanCollide = false; c.Massless = true",
            "            c.Parent = tool",
            "            local w = Instance.new('WeldConstraint')",
            "            w.Part0 = handle; w.Part1 = c; w.Parent = c",
            "        end",
            "    end",
            "    tool.Parent = game:GetService('StarterPack')",
            "    return tool",
            "end",
            "-- Décommentez la ligne suivante pour placer directement l'arme dans StarterPack :",
            "-- ConvertToTool(model)",
        ]
    lines.append(f"print('[3d-forge v5] Asset Roblox Studio prêt : {clean_name} !')")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# 6. Export Complet Game-Ready Multi-Moteurs (`export_game_package`)
# --------------------------------------------------------------------------- #

def _extract_uv_pbr_vertices(mesh_in: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Extrait `(albedo, rough, metal)` aux sommets d'un maillage texturé UV s'il possède une texture PBR."""
    uv_h = getattr(mesh_in.visual, "uv", None)
    mat_h = getattr(mesh_in.visual, "material", None)
    tex_h = getattr(mat_h, "baseColorTexture", None) if mat_h is not None else None
    mr_h = getattr(mat_h, "metallicRoughnessTexture", None) if mat_h is not None else None
    if uv_h is None or tex_h is None:
        return None
    arr_t = np.asarray(tex_h.convert("RGB"), dtype=np.float32) / 255.0
    th, tw, _ = arr_t.shape
    px_x = np.clip((uv_h[:, 0] * (tw - 1)).round().astype(np.int32), 0, tw - 1)
    px_y = np.clip(((1.0 - uv_h[:, 1]) * (th - 1)).round().astype(np.int32), 0, th - 1)
    v_a = arr_t[px_y, px_x]
    if mr_h is not None:
        arr_m = np.asarray(mr_h.convert("RGB"), dtype=np.float32) / 255.0
        v_r = arr_m[px_y, px_x, 1]
        v_m = arr_m[px_y, px_x, 2]
    else:
        v_r = np.full(len(mesh_in.vertices), 0.50, dtype=np.float32)
        v_m = np.full(len(mesh_in.vertices), 0.15, dtype=np.float32)
    return v_a, v_r, v_m


def _qa_scale_bar(im: Image.Image, extents_m) -> Image.Image:
    """Barre d'échelle calibrée sur le cadrage auto de `renderer.render_view`
    (sphère englobante de rayon r à d = 3.1 r, fov 38° => ~93.7 % de la hauteur)."""
    import math as _m
    d = ImageDraw.Draw(im)
    W, H = im.size
    r = float(np.linalg.norm(extents_m)) / 2.0
    px_per_m = (0.937 * H) / (2.0 * r) if r > 1e-9 else 0.0
    target = 0.32 * W / max(px_per_m, 1e-9)
    k = 10.0 ** _m.floor(_m.log10(max(target, 1e-9)))
    bar_m = max([c * k for c in (0.1, 0.2, 0.5, 1.0) if c * k <= target * 1.05] or [k])
    x0, y0 = int(0.06 * W), H - int(0.07 * H)
    x1 = x0 + max(int(bar_m * px_per_m), 4)
    d.line((x0, y0, x1, y0), fill=(15, 15, 15), width=7)
    d.line((x0, y0, x1, y0), fill=(252, 252, 252), width=3)
    for xx in (x0, x1):
        d.line((xx, y0 - 8, xx, y0 + 8), fill=(252, 252, 252), width=3)
    lbl = f"{bar_m * 100:.0f} cm | {bar_m * ROBLOX_STUDS_PER_METER:.2f} Stud"
    f = renderer._font(15)
    tw = int(d.textlength(lbl, font=f)) + 10
    d.rectangle((x0, y0 - 30, x0 + tw, y0 - 10), fill=(16, 20, 16))
    d.text((x0 + 5, y0 - 28), lbl, fill=(140, 240, 170), font=f)
    return im


def _qa_metrics_card(clean_name: str, lines: list) -> Image.Image:
    card = Image.new("RGB", (480, 480), (16, 18, 22))
    d = ImageDraw.Draw(card)
    d.text((14, 12), f"Carte QA — {clean_name}", fill=(235, 235, 240), font=renderer._font(20))
    y = 52
    for ln in lines:
        d.text((14, y), ln, fill=(205, 210, 220), font=renderer._font(15))
        y += 23
    d.text((14, 448), "gates complètes : python3 scripts/gates.py <dossier>",
           fill=(140, 240, 170), font=renderer._font(15))
    return card


def export_game_package(
    source: mk.Builder | trimesh.Trimesh | str | Path,
    out_dir: str | Path,
    name: str | None = None,
    engine: str = "roblox_unreal",
    lod0_tris: int = 3200,
    tex_size: int = 1024,
    weathering: bool = True,
    delight_pass: bool | None = None,
    webp: bool = True,
    decal_strength: float = 0.65,
    roblox_scale: str = "studs",
    ai_views: dict[str, str | Path] | None = None,
    joint_tex_size: int | None = None,
    dirt_amount: float = 0.36,
    grime_amount: float = 0.22,
) -> dict:
    """Pipeline de bout en bout produisant un asset Game-Ready complet (`v5.1`) :
      - Fusionne les Draw Calls statiques opaques + cuit les sous-ensembles articulés en PBR complet,
      - Préserve automatiquement les textures procédurales HD `source._baked_scene` (`tsuka-maki`, `hamon`...),
      - Cuit High-Poly -> Low-Poly `LOD0` + génère `LOD1` (`40%`) et `LOD2` (`15%`),
      - Supporte la projection Z-buffer multi-vues GPU Datacenter (`ai_views`) et le mode Dual-1024² Roblox !
    """
    t0 = time.perf_counter()
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    if isinstance(source, str) and not Path(source).exists():
        import inspect
        import generate as _gen
        rec = _gen.get_recipe(source)
        if rec is not None:
            if name is None:
                name = source
            mk.set_quality(1.0)
            fn_b = rec["builder"]
            # Saute tout pré-bake UV redondant (`textured=False`) puisque `game_ready` cuit
            # directement ses cartes `1024²` sémantiques depuis la géométrie analytique !
            if "textured" in inspect.signature(fn_b).parameters:
                source = fn_b(textured=False)
            else:
                source = fn_b()
    if name is None:
        if isinstance(source, mk.Builder):
            name = source.name
        elif isinstance(source, (str, Path)):
            name = Path(source).stem
        else:
            name = "game_asset"
    clean_name = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)

    joints = {}
    declared_sockets = {}
    glass_parts: list[tuple[trimesh.Trimesh, mk.Material, str]] = []
    neon_parts_raw: list[tuple[trimesh.Trimesh, mk.Material, str]] = []
    joint_opaque_groups: dict[str, list[tuple[trimesh.Trimesh, mk.Material, str]]] = {}
    static_meshes: list[trimesh.Trimesh] = []
    static_albedo: list[np.ndarray] = []
    static_rough: list[np.ndarray] = []
    static_metal: list[np.ndarray] = []
    static_mat_id: list[np.ndarray] = []
    static_part_entries: list[tuple[trimesh.Trimesh, mk.Material, str, int]] = []
    collider_inputs: list[trimesh.Trimesh] = []
    raw_draw_calls = 1
    has_prebaked_uv = False
    # v5.7 — défini pour TOUS les chemins d'entrée (Builder ET fichier externe).
    all_glass_asset = False
    glass_tint_value = None
    ao_ext_override = None
    curv_ext_override = None

    if isinstance(source, mk.Builder):
        raw_draw_calls = len(source.parts)
        joints = dict(source._joints)
        declared_sockets = dict(source._sockets)
        for idx, (m, mat_o, lbl) in enumerate(source.parts):
            mat_use = mat_o or mk.Material("default", "#9a9da2", 0.0, 0.5)
            grp = source._part_groups.get(idx)
            collider_inputs.append(m.copy())
            em_vec = getattr(mat_use, "emissive", None)
            em_val = float(getattr(mat_use, "emissive_strength", 0.0) or 0.0)
            if em_vec is not None and np.max(np.asarray(em_vec)) > 0.05:
                em_val = max(em_val, float(np.max(np.asarray(em_vec))))
            if mat_use.opacity < 0.999:
                glass_parts.append((m.copy(), mat_use, lbl))
            elif em_val > 0.05 and grp is None:
                neon_parts_raw.append((m.copy(), mat_use, lbl))
            elif grp:
                joint_opaque_groups.setdefault(grp, []).append((m.copy(), mat_use, lbl))
            else:
                nv = len(m.vertices)
                mid_val = classify_material_id(mat_use, lbl)
                static_meshes.append(m.copy())
                static_albedo.append(np.tile(np.asarray(mat_use.color, dtype=np.float32), (nv, 1)))
                static_rough.append(np.full(nv, float(mat_use.roughness), dtype=np.float32))
                static_metal.append(np.full(nv, float(mat_use.metallic), dtype=np.float32))
                static_mat_id.append(np.full(nv, mid_val, dtype=np.int32))
                static_part_entries.append((m.copy(), mat_use, lbl, mid_val))

        # v5.7 — un asset ENTIÈREMENT en verre (verre à vin) envoyait toutes ses
        # pièces dans `glass_parts` : `static_meshes` restait vide et
        # `np.concatenate([])` cassait tout le build. On garde le verre comme
        # matériau à transmission, et on cuisait quand même une surface de
        # support (surface de verre solide, albédo/rugosité du matériau) pour
        # que l'atlas, les LOD et les gates restent mesurables.
        if not static_meshes:
            for gm, gmat, glbl in glass_parts:
                nv = len(gm.vertices)
                static_meshes.append(gm.copy())
                static_albedo.append(np.tile(np.asarray(gmat.color, dtype=np.float32), (nv, 1)))
                static_rough.append(np.full(nv, float(gmat.roughness), dtype=np.float32))
                static_metal.append(np.zeros(nv, dtype=np.float32))
                static_mat_id.append(np.full(nv, classify_material_id(gmat, glbl), dtype=np.int32))
                static_part_entries.append((gm.copy(), gmat, glbl,
                                            classify_material_id(gmat, glbl)))
            raw_concat = trimesh.util.concatenate(static_meshes)
            v_mid_raw = np.concatenate(static_mat_id)
            high_body = raw_concat
            v_alb = np.vstack(static_albedo)
            v_rgh = np.concatenate(static_rough)
            v_mtl = np.concatenate(static_metal)
            v_mid = v_mid_raw
            glass_parts = []          # exporté via l'atlas PBR, pas de double pièce
            all_glass_asset = True
        else:
            raw_concat = trimesh.util.concatenate(static_meshes)
            v_mid_raw = np.concatenate(static_mat_id)
            high_body = raw_concat
            v_alb = np.vstack(static_albedo)
            v_rgh = np.concatenate(static_rough)
            v_mtl = np.concatenate(static_metal)
            v_mid = v_mid_raw
            all_glass_asset = False
        union_solid_body = mk.union(static_meshes) if len(static_meshes) > 1 else static_meshes[0]
        if (
            not all_glass_asset
            and len(static_part_entries) > 1
            and len(union_solid_body.faces) >= 12
        ):
            try:
                (
                    high_body,
                    v_alb,
                    v_rgh,
                    v_mtl,
                    v_mid,
                    ao_ext_override,
                    curv_ext_override,
                ) = _build_exterior_high_poly_from_union(union_solid_body, static_part_entries)
            except Exception:
                pass
        # Décimation adaptative préservant la finesse anatomique des yeux/paupières/pupilles :
        # en QEM uniforme, l'erreur quadrique varie en ~L⁴ (arête de 1,5 mm sur une pupille vs
        # 25 mm sur un crâne = poids 70 000× plus faible !), ce qui écrase les yeux en facettes.
        def _is_anatomical_eye_part(lbl_s: str) -> bool:
            low_s = lbl_s.lower()
            if "eyelet" in low_s or "eyebolt" in low_s:
                return False
            if any(tok in low_s for tok in ("eyeball", "eyelid", "pupil", "iris", "cornea", "sclera", "glint")):
                return True
            parts_s = [p for p in low_s.replace("-", "_").split("_") if p]
            return "eye" in parts_s or "eyes" in parts_s

        eye_meshes = [pm for pm, _pmat, plbl, _pmid in static_part_entries if _is_anatomical_eye_part(plbl)]
        body_meshes = [pm for pm, _pmat, plbl, _pmid in static_part_entries if not _is_anatomical_eye_part(plbl)]
        if eye_meshes and body_meshes and lod0_tris >= 800:
            eye_solid = mk.union(eye_meshes) if len(eye_meshes) > 1 else eye_meshes[0]
            body_solid = mk.union(body_meshes) if len(body_meshes) > 1 else body_meshes[0]
            # Supprime l'hémisphère arrière caché dans le crâne : 100 % des triangles et texels UV
            # sont concentrés sur la cornée visible, le bord circulaire de pupille et les paupières !
            eye_visible = mk.difference(eye_solid, [body_solid])
            if len(eye_visible.faces) >= 24:
                eye_budget = min(len(eye_visible.faces), max(280, int(lod0_tris * 0.16)))
                body_budget = max(240, int(lod0_tris) - eye_budget)
                low_body = decimate_mesh_clean(body_solid, body_budget)
                low_eyes = decimate_mesh_clean(eye_visible, eye_budget)
                low_base = trimesh.util.concatenate([low_body, low_eyes])
            else:
                low_base = decimate_mesh_clean(union_solid_body, lod0_tris)
        elif not ai_views and len(static_part_entries) >= 3 and lod0_tris >= 3200:
            # Décimation multi-matériaux propre : regroupe par matériau PBR identique afin
            # d'éliminer 100 % des bavures d'atlas UV aux frontières métal/plastique/caoutchouc
            # et préserver les détails fins (boulons, ailettes, durites) via pondération `sqrt` !
            mat_buckets: dict[tuple, list[trimesh.Trimesh]] = {}
            for pm, pmat, _plbl, pmid in static_part_entries:
                c_key = tuple(np.round(np.asarray(pmat.color, dtype=np.float32), 2).tolist())
                m_key = (c_key, round(float(pmat.roughness), 2), round(float(pmat.metallic), 2), int(pmid))
                mat_buckets.setdefault(m_key, []).append(pm)
            if len(mat_buckets) >= 2:
                b_solids = [mk.union(ms) if len(ms) > 1 else ms[0] for ms in mat_buckets.values()]
                b_weights = np.array([math.sqrt(max(len(s_m.faces), 12)) for s_m in b_solids], dtype=np.float64)
                b_weights /= max(float(b_weights.sum()), 1e-9)
                low_parts = [
                    decimate_mesh_clean(s_m, max(int(round(lod0_tris * w_b)), 36))
                    for s_m, w_b in zip(b_solids, b_weights)
                ]
                low_base = trimesh.util.concatenate(low_parts)
                if len(low_base.faces) > lod0_tris:
                    low_base = decimate_mesh_clean(low_base, lod0_tris)
            else:
                low_base = decimate_mesh_clean(union_solid_body, lod0_tris)
        else:
            low_base = decimate_mesh_clean(union_solid_body, lod0_tris)
        if delight_pass is None:
            delight_pass = False
    else:
        src_obj = trimesh.load(source, force="scene") if isinstance(source, (str, Path)) else source
        if isinstance(src_obj, trimesh.Scene):
            raw_draw_calls = max(len(src_obj.geometry), 1)
            high_body = src_obj.to_geometry()
        else:
            high_body = src_obj.copy()
        collider_inputs = [high_body.copy()]
        ext_uv = _extract_uv_pbr_vertices(high_body)
        nv = len(high_body.vertices)
        if ext_uv is not None:
            v_alb, v_rgh, v_mtl = ext_uv
            has_prebaked_uv = True
        else:
            v_alb = np.tile(np.array([0.55, 0.56, 0.58], dtype=np.float32), (nv, 1))
            v_rgh = np.full(nv, 0.50, dtype=np.float32)
            v_mtl = np.full(nv, 0.10, dtype=np.float32)
        v_mid = np.where(v_mtl > 0.72, MAT_BRUSHED_STEEL,
                         np.where(v_rgh > 0.68, MAT_RUBBER_POLY, MAT_CLEAN_ENAMEL)).astype(np.int32)
        low_base = decimate_mesh_clean(high_body, lod0_tris)
        if delight_pass is None:
            delight_pass = not has_prebaked_uv

    from concurrent.futures import ThreadPoolExecutor

    use_weather = weathering and (not has_prebaked_uv)
    if all_glass_asset and glass_tint_value is None:
        glass_tint_value = np.array([0.86, 0.94, 0.97, 0.30], dtype=np.float32)
    hp_cache = prepare_high_poly_sampler(
        high_body, v_alb, v_rgh, v_mtl, v_mid,
        ao_override=ao_ext_override, curv_override=curv_ext_override,
    )

    def _bake_body_task() -> dict:
        return bake_high_to_low(
            high_body, v_alb, v_rgh, v_mtl, low_base,
            high_vertex_mat_id=v_mid, ai_views=ai_views, hp_cache=hp_cache,
            tex_size=tex_size, weathering=use_weather,
            delight_pass=bool(delight_pass), decal_strength=decal_strength,
            dirt_amount=dirt_amount, grime_amount=grime_amount,
            glass_only=bool(all_glass_asset),
            glass_tint=glass_tint_value,
        )

    def _bake_joint_task(grp_item: tuple[str, list]) -> tuple[str, dict]:
        grp, plist = grp_item
        j_hi = trimesh.util.concatenate([p[0] for p in plist])
        j_alb = np.vstack([np.tile(np.asarray(p[1].color, dtype=np.float32), (len(p[0].vertices), 1)) for p in plist])
        j_rgh = np.concatenate([np.full(len(p[0].vertices), float(p[1].roughness), dtype=np.float32) for p in plist])
        j_mtl = np.concatenate([np.full(len(p[0].vertices), float(p[1].metallic), dtype=np.float32) for p in plist])
        j_mid = np.concatenate([np.full(len(p[0].vertices), classify_material_id(p[1], p[2]), dtype=np.int32) for p in plist])
        j_target = max(int(lod0_tris * 0.68), 320)
        if len(plist) > 1:
            # Alloue les budgets proportionnellement à sqrt(faces) avec marge de 0.92 pour ne JAMAIS
            # repasser `j_low` concaténé dans `decimate_mesh_clean` (qui ne garderait que la plus grosse composante
            # connexe et supprimerait les rayons / moyeux séparés d'une roue !).
            weights = np.array([math.sqrt(max(len(p[0].faces), 12)) for p in plist], dtype=np.float64)
            weights = (weights / max(float(weights.sum()), 1e-9)) * 0.92
            j_parts_low = [
                decimate_mesh_clean(p[0], max(int(round(j_target * w)), 32))
                for p, w in zip(plist, weights)
            ]
            j_low = trimesh.util.concatenate(j_parts_low)
        else:
            j_low = decimate_mesh_clean(plist[0][0], j_target)
        j_res = bake_high_to_low(
            j_hi, j_alb, j_rgh, j_mtl, j_low,
            high_vertex_mat_id=j_mid, ai_views=ai_views,
            tex_size=int(joint_tex_size) if joint_tex_size is not None else max(tex_size // 2, 512),
            weathering=weathering,
            delight_pass=bool(delight_pass), decal_strength=decal_strength,
        )
        return grp, j_res

    joint_baked_map: dict[str, dict] = {}
    if joint_opaque_groups:
        with ThreadPoolExecutor(max_workers=1 + len(joint_opaque_groups)) as ex:
            fut_body = ex.submit(_bake_body_task)
            fut_joints = [ex.submit(_bake_joint_task, item) for item in joint_opaque_groups.items()]
            baked = fut_body.result()
            for fj in fut_joints:
                gk, gv = fj.result()
                joint_baked_map[gk] = gv
    else:
        baked = _bake_body_task()

    lod0_mesh = baked["mesh_lod0"]

    # `LOD1` (40%) et `LOD2` (21% direct depuis le solide soudé : `LOD0 > LOD1 > LOD2 > 50` 100 % garanti !)
    lod_src = union_solid_body if "union_solid_body" in locals() and union_solid_body is not None else low_base
    n_lod0 = len(lod0_mesh.faces)
    t_lod1 = min(max(n_lod0 - 8, 64), max(min(int(lod0_tris * 0.40), int(n_lod0 * 0.68)), 76))
    t_lod2 = min(max(t_lod1 - 8, 54), max(min(int(lod0_tris * 0.21), int(t_lod1 * 0.65)), 58))
    lod1_raw = decimate_mesh_clean(lod_src, t_lod1)
    lod2_raw = decimate_mesh_clean(lod1_raw, t_lod2)
    lod1_mesh = build_shared_atlas_lod(lod0_mesh, baked, lod1_raw, max(tex_size // 2, 256))
    # v5.2 : le LOD2 reçoit SON PROPRE bake 128² (atlas, AO et normales cohérents
    # avec sa surface décimée). Partager l'atlas du LOD0 avec des triangles géants
    # fait interpoler les UV à travers les charts (« vitrage brisé » sur la QA).
    lod2_baked = bake_high_to_low(
        high_body, v_alb, v_rgh, v_mtl, lod2_raw,
        high_vertex_mat_id=v_mid, ai_views=ai_views, hp_cache=hp_cache,
        tex_size=max(tex_size // 4, 128), weathering=use_weather,
        delight_pass=False, decal_strength=decal_strength,
    )
    lod2_mesh = lod2_baked["mesh_lod0"]

    # Construit la scène principale `LOD0` fusionnée en Draw Calls minimaux !
    def _assemble_lod_scene(body_mesh: trimesh.Trimesh, include_colliders: str | None = None) -> trimesh.Scene:
        sc = trimesh.Scene(base_frame=f"SM_{clean_name}")
        sc.add_geometry(body_mesh.copy(), node_name=f"SM_{clean_name}_Body", geom_name=f"SM_{clean_name}_Body")

        if glass_parts:
            g_merged = trimesh.util.concatenate([g[0] for g in glass_parts])
            g_merged.visual = trimesh.visual.TextureVisuals(material=glass_parts[0][1].to_pbr())
            sc.add_geometry(g_merged, node_name=f"SM_{clean_name}_Glass", geom_name=f"SM_{clean_name}_Glass")

        for nm_m, nm_mat, nm_lbl in neon_parts_raw:
            safe_lbl = "".join(c if c.isalnum() or c == "_" else "_" for c in nm_lbl)
            n_copy = decimate_mesh_clean(nm_m.copy(), 600)
            n_copy.visual = trimesh.visual.TextureVisuals(material=nm_mat.to_pbr())
            sc.add_geometry(n_copy, node_name=f"Neon_{safe_lbl}", geom_name=f"Neon_{safe_lbl}")

        # Hiérarchie d'articulations : tri topologique pour enregistrer les joints parents AVANT les enfants !
        ordered_joints = sorted(
            joint_opaque_groups.items(),
            key=lambda kv: 1 if joints.get(kv[0], {}).get("parent") else 0,
        )
        for grp, plist in ordered_joints:
            j_meta = joints.get(grp, {})
            piv = np.asarray(j_meta.get("pivot", [0.0, 0.0, 0.0]), dtype=float)
            parent_grp = j_meta.get("parent")
            if parent_grp and parent_grp in joint_opaque_groups:
                parent_piv = np.asarray(joints.get(parent_grp, {}).get("pivot", [0.0, 0.0, 0.0]), dtype=float)
                T = np.eye(4, dtype=float)
                T[:3, 3] = piv - parent_piv
                sc.graph.update(frame_to=grp, frame_from=parent_grp, matrix=T)
            else:
                T = np.eye(4, dtype=float)
                T[:3, 3] = piv
                sc.graph.update(frame_to=grp, frame_from=sc.graph.base_frame, matrix=T)
            j_mesh = joint_baked_map[grp]["mesh_lod0"].copy()
            j_mesh.apply_translation([-piv[0], -piv[1], -piv[2]])
            sc.add_geometry(j_mesh, node_name=f"{grp}_mesh", geom_name=f"{grp}_mesh", parent_node_name=grp)

        if include_colliders:
            for ci, hull in enumerate(colliders):
                cname = f"UCX_SM_{clean_name}_{ci:02d}" if include_colliders == "unreal" else f"{clean_name}_col_{ci:02d}-colonly"
                h_copy = hull.copy()
                h_copy.visual = trimesh.visual.TextureVisuals(
                    material=mk.Material(f"col_mat_{ci}", "#35e085", 0.0, 0.6, opacity=0.28).to_pbr()
                )
                sc.add_geometry(h_copy, node_name=cname, geom_name=cname)

        sc.metadata["joints"] = joints
        sc.metadata["sockets"] = sockets
        return sc

    all_bounds = np.vstack([
        np.min([m.bounds[0] for m in collider_inputs], axis=0),
        np.max([m.bounds[1] for m in collider_inputs], axis=0),
    ])
    colliders = generate_convex_colliders(collider_inputs, max_hulls=6, max_tris_per_hull=64)
    sockets = infer_gameplay_sockets(clean_name, all_bounds, joints=joints, declared=declared_sockets)

    sc_lod0 = _assemble_lod_scene(lod0_mesh)
    sc_lod1 = _assemble_lod_scene(lod1_mesh)
    sc_lod2 = _assemble_lod_scene(lod2_mesh)
    final_draw_calls = len(sc_lod0.geometry)

    glb_main = out_path / f"{clean_name}_game.glb"
    glb_lod1 = out_path / f"{clean_name}_LOD1.glb"
    glb_lod2 = out_path / f"{clean_name}_LOD2.glb"
    mk.export_glb_pbr(sc_lod0, str(glb_main), webp=webp)
    mk.export_glb_pbr(sc_lod1, str(glb_lod1), webp=webp)
    mk.export_glb_pbr(sc_lod2, str(glb_lod2), webp=webp)

    # Export collision autonome + profils moteurs dédiés (`unreal`, `unity`, `godot`)
    col_scene = trimesh.Scene([h.copy() for h in colliders])
    col_glb = out_path / f"{clean_name}_colliders.glb"
    col_scene.export(str(col_glb))

    if engine == "all":
        engines = {"roblox", "unreal", "unity", "godot"}
    elif engine == "roblox_unreal":
        engines = {"roblox", "unreal"}
    else:
        engines = {engine}
    exported_profiles = {}

    if "roblox" in engines:
        rbx_dir = out_path / "roblox"
        rbx_dir.mkdir(exist_ok=True)
        scale_k = ROBLOX_STUDS_PER_METER if roblox_scale == "studs" else 1.0
        rbx_res = min(int(tex_size), ROBLOX_MAX_TEX_SIZE)

        def _make_rbx_material(b_res: dict, mat_tag: str, res_px: int) -> tuple[trimesh.visual.material.PBRMaterial, Image.Image, Image.Image, Image.Image, Image.Image]:
            a_np = np.asarray(b_res["albedo"], dtype=np.float32) / 255.0
            o_np = np.asarray(b_res["orm"], dtype=np.float32) / 255.0
            c_u8 = np.clip(a_np * (0.30 + 0.70 * o_np[..., 0:1]) * 255.0, 0.0, 255.0).round().astype(np.uint8)
            c_im = Image.fromarray(c_u8, mode="RGB")
            n_im = b_res["normal_gl"]
            r_im = Image.fromarray(np.asarray(b_res["orm"])[..., 1], mode="L")
            m_im = Image.fromarray(np.asarray(b_res["orm"])[..., 2], mode="L")
            if c_im.size != (res_px, res_px):
                c_im = c_im.resize((res_px, res_px), Image.Resampling.LANCZOS)
                n_im = n_im.resize((res_px, res_px), Image.Resampling.LANCZOS)
                r_im = r_im.resize((res_px, res_px), Image.Resampling.LANCZOS)
                m_im = m_im.resize((res_px, res_px), Image.Resampling.LANCZOS)
            mat_pbr = trimesh.visual.material.PBRMaterial(
                name=f"{mat_tag}_SurfaceAppearance",
                baseColorTexture=c_im,
                metallicRoughnessTexture=b_res["orm"].resize((res_px, res_px), Image.Resampling.LANCZOS),
                normalTexture=n_im,
                metallicFactor=1.0,
                roughnessFactor=1.0,
            )
            return mat_pbr, c_im, n_im, m_im, r_im

        rbx_pbr_mat, rbx_col_img, rbx_nrm_img, rbx_mtl_img, rbx_rgh_img = _make_rbx_material(baked, clean_name, rbx_res)

        p_col = rbx_dir / f"T_{clean_name}_ColorMap.png"
        p_nrm = rbx_dir / f"T_{clean_name}_NormalMap.png"
        p_mtl = rbx_dir / f"T_{clean_name}_MetalnessMap.png"
        p_rgh = rbx_dir / f"T_{clean_name}_RoughnessMap.png"
        rbx_col_img.save(p_col, compress_level=2)
        rbx_nrm_img.save(p_nrm, compress_level=2)
        rbx_mtl_img.save(p_mtl, compress_level=2)
        rbx_rgh_img.save(p_rgh, compress_level=2)

        sc_rbx = trimesh.Scene(base_frame=f"{clean_name}_roblox")

        # MODE HAUTE DENSITÉ TEXELS ROBLOX (`v5.1` Dual-1024² `SurfaceAppearance`) :
        # Bake parallèle multi-cœurs (`Blade` + `Hilt`) en réutilisant `hp_cache` !
        sorted_spans = np.sort(all_bounds[1] - all_bounds[0])[::-1]
        is_elongated_weapon = (
            len(static_part_entries) >= 2
            and float(sorted_spans[0]) / max(float(sorted_spans[1]), 1e-4) >= 4.2
        )
        rbx_hd_zones = {}
        if is_elongated_weapon:
            blade_parts = [e for e in static_part_entries if any(k in e[2].lower() for k in ("blade", "fuller", "edge", "tip"))]
            hilt_parts = [e for e in static_part_entries if e not in blade_parts]
            if blade_parts and hilt_parts:
                def _bake_zone_worker(zname_entries):
                    zn, zent = zname_entries
                    z_meshes = [e[0].copy() for e in zent]
                    z_low = decimate_mesh_clean(
                        mk.union(z_meshes) if len(z_meshes) > 1 else z_meshes[0],
                        min(ROBLOX_MAX_TRIS_PER_PART - 200, max(lod0_tris // 2, 900)),
                    )
                    z_baked = bake_high_to_low(
                        high_body, v_alb, v_rgh, v_mtl, z_low,
                        high_vertex_mat_id=v_mid, ai_views=ai_views, hp_cache=hp_cache,
                        tex_size=ROBLOX_MAX_TEX_SIZE, weathering=use_weather,
                        delight_pass=bool(delight_pass), decal_strength=decal_strength,
                    )
                    z_mat, z_col, z_nrm, z_mtl, z_rgh = _make_rbx_material(z_baked, f"{clean_name}_{zn}", ROBLOX_MAX_TEX_SIZE)
                    z_col.save(rbx_dir / f"T_{clean_name}_{zn}_ColorMap.png", compress_level=2)
                    z_nrm.save(rbx_dir / f"T_{clean_name}_{zn}_NormalMap.png", compress_level=2)
                    z_mtl.save(rbx_dir / f"T_{clean_name}_{zn}_MetalnessMap.png", compress_level=2)
                    z_rgh.save(rbx_dir / f"T_{clean_name}_{zn}_RoughnessMap.png", compress_level=2)
                    zm = z_baked["mesh_lod0"].copy()
                    zm.apply_scale(scale_k)
                    zm.visual = trimesh.visual.TextureVisuals(uv=np.asarray(z_baked["mesh_lod0"].visual.uv, dtype=np.float64), material=z_mat)
                    return zn, zm

                with ThreadPoolExecutor(max_workers=2) as zpool:
                    for zname, zm in zpool.map(_bake_zone_worker, [("Blade", blade_parts), ("Hilt", hilt_parts)]):
                        sc_rbx.add_geometry(zm, node_name=f"{clean_name}_{zname}", geom_name=f"{clean_name}_{zname}")
                        rbx_hd_zones[zname] = int(len(zm.faces))

        if not rbx_hd_zones:
            rbx_body = lod0_mesh.copy()
            if len(rbx_body.faces) > ROBLOX_MAX_TRIS_PER_PART:
                rbx_raw = decimate_mesh_clean(low_base, ROBLOX_MAX_TRIS_PER_PART - 200)
                rbx_body = bake_high_to_low(
                    high_body, v_alb, v_rgh, v_mtl, rbx_raw,
                    high_vertex_mat_id=v_mid, ai_views=ai_views, hp_cache=hp_cache,
                    tex_size=rbx_res, weathering=use_weather,
                    delight_pass=bool(delight_pass), decal_strength=decal_strength,
                )["mesh_lod0"]
            rbx_body.apply_scale(scale_k)
            rbx_body.visual = trimesh.visual.TextureVisuals(
                uv=np.asarray(lod0_mesh.visual.uv, dtype=np.float64),
                material=rbx_pbr_mat,
            )
            sc_rbx.add_geometry(rbx_body, node_name=f"{clean_name}_Body", geom_name=f"{clean_name}_Body")

        neon_meta = []
        for nm_m, nm_mat, nm_lbl in neon_parts_raw:
            safe_lbl = "".join(c if c.isalnum() or c == "_" else "_" for c in nm_lbl)
            part_nm = f"Neon_{safe_lbl}"
            nc = decimate_mesh_clean(nm_m.copy(), min(ROBLOX_MAX_TRIS_PER_PART, 600))
            nc.apply_scale(scale_k)
            nc.visual = trimesh.visual.TextureVisuals(material=nm_mat.to_pbr())
            sc_rbx.add_geometry(nc, node_name=part_nm, geom_name=part_nm)
            em_c = np.asarray(getattr(nm_mat, "emissive", nm_mat.color[:3]), dtype=np.float32)[:3]
            if float(em_c.max()) <= 1e-4:
                em_c = np.asarray(nm_mat.color[:3], dtype=np.float32)
            em_c = em_c / max(float(em_c.max()), 1.0)
            neon_meta.append({
                "name": part_nm,
                "rgb255": [int(round(x * 255)) for x in np.clip(em_c, 0.0, 1.0)],
            })

        if glass_parts:
            gm = decimate_mesh_clean(trimesh.util.concatenate([g[0] for g in glass_parts]), ROBLOX_MAX_TRIS_PER_PART)
            gm.apply_scale(scale_k)
            gm.visual = trimesh.visual.TextureVisuals(material=glass_parts[0][1].to_pbr())
            sc_rbx.add_geometry(gm, node_name=f"Glass_{clean_name}", geom_name=f"Glass_{clean_name}")

        joints_studs = {}
        for grp, plist in joint_opaque_groups.items():
            piv_s = [float(c) * scale_k for c in joints.get(grp, {}).get("pivot", [0.0, 0.0, 0.0])]
            T = np.eye(4, dtype=float)
            T[:3, 3] = piv_s
            sc_rbx.graph.update(frame_to=grp, frame_from=sc_rbx.graph.base_frame, matrix=T)
            jb = joint_baked_map[grp]
            j_mat, _, _, _, _ = _make_rbx_material(jb, f"{clean_name}_{grp}", max(rbx_res // 2, 512))
            jm = jb["mesh_lod0"].copy()
            jm.apply_scale(scale_k)
            jm.apply_translation([-piv_s[0], -piv_s[1], -piv_s[2]])
            jm.visual = trimesh.visual.TextureVisuals(uv=np.asarray(jb["mesh_lod0"].visual.uv, dtype=np.float64), material=j_mat)
            sc_rbx.add_geometry(jm, node_name=f"{grp}_mesh", geom_name=f"{grp}_mesh", parent_node_name=grp)
            joints_studs[grp] = {
                "pivot_studs": piv_s,
                "axis": joints.get(grp, {}).get("axis", [1.0, 0.0, 0.0]),
            }

        sockets_studs_map = {}
        rbx_sockets_gltf = {}
        for sname, sinfo in sockets.items():
            sp_s = [round(float(v) * scale_k, 5) for v in sinfo["position"]]
            sockets_studs_map[sname] = sp_s
            rbx_sockets_gltf[sname] = {"position": sp_s, "rotation_deg": sinfo.get("rotation_deg", [0, 0, 0])}
        sc_rbx.metadata["sockets"] = rbx_sockets_gltf
        sc_rbx.metadata["joints"] = {
            k: {"pivot": v["pivot_studs"], "axis": v["axis"], "kind": "revolute"}
            for k, v in joints_studs.items()
        }

        rbx_glb = rbx_dir / f"{clean_name}_roblox.glb"
        # CRITIQUE ROBLOX : `webp=False` obligatoire pour que l'Import 3D Roblox Studio lise 100 % des textures !
        mk.export_glb_pbr(sc_rbx, str(rbx_glb), webp=False)

        size_studs = [round(float(x) * scale_k, 3) for x in (all_bounds[1] - all_bounds[0])]
        max_part_tris = max(len(g.faces) for g in sc_rbx.geometry.values())
        luau_path = rbx_dir / f"setup_{clean_name}.lua"
        luau_path.write_text(
            _generate_roblox_luau_script(clean_name, size_studs, sockets_studs_map, neon_meta, joints_studs),
            encoding="utf-8",
        )
        exported_profiles["roblox"] = {
            "studio_ready_glb_png": str(rbx_glb),
            "scale_unit": roblox_scale,
            "size_studs_xyz": size_studs,
            "max_part_tris": int(max_part_tris),
            "under_10k_tris_limit": bool(max_part_tris < 10_000),
            "surface_appearance": {
                "ColorMap": str(p_col),
                "NormalMap": str(p_nrm),
                "MetalnessMap": str(p_mtl),
                "RoughnessMap": str(p_rgh),
            },
            "neon_parts": [n["name"] for n in neon_meta],
            "luau_setup_script": str(luau_path),
        }

    if "unreal" in engines:
        ue_dir = out_path / "unreal"
        ue_dir.mkdir(exist_ok=True)
        baked["albedo"].save(ue_dir / f"T_{clean_name}_BC.png", compress_level=2)
        baked["orm"].save(ue_dir / f"T_{clean_name}_ORM.png", compress_level=2)
        baked["normal_dx"].save(ue_dir / f"T_{clean_name}_N.png", compress_level=2)  # DirectX -Y !
        # Jumelle OpenGL de la MÊME cuisson : c'est elle qui rend la polarité
        # `-Y` vérifiable pixel à pixel (gates `normal_dx_vs_gl`). Sans elle, la
        # gate ne pouvait comparer que des atlas de résolutions/UV différents.
        baked["normal_gl"].save(ue_dir / f"T_{clean_name}_N_gl.png", compress_level=2)
        sc_ue = _assemble_lod_scene(lod0_mesh, include_colliders="unreal")
        ue_glb = ue_dir / f"SM_{clean_name}.glb"
        mk.export_glb_pbr(sc_ue, str(ue_glb), webp=False)
        exported_profiles["unreal"] = {
            "static_mesh_with_ucx": str(ue_glb),
            "base_color": str(ue_dir / f"T_{clean_name}_BC.png"),
            "orm_packed": str(ue_dir / f"T_{clean_name}_ORM.png"),
            "normal_directx_neg_y": str(ue_dir / f"T_{clean_name}_N.png"),
            "normal_opengl_pos_y": str(ue_dir / f"T_{clean_name}_N_gl.png"),
        }

    if "unity" in engines:
        un_dir = out_path / "unity"
        un_dir.mkdir(exist_ok=True)
        baked["albedo"].save(un_dir / f"T_{clean_name}_BaseMap.png", compress_level=2)
        baked["unity_mask"].save(un_dir / f"T_{clean_name}_MaskMap.png", compress_level=2)
        baked["normal_gl"].save(un_dir / f"T_{clean_name}_NormalGL.png", compress_level=2)
        exported_profiles["unity"] = {
            "prefab_glb": str(glb_main),
            "base_map": str(un_dir / f"T_{clean_name}_BaseMap.png"),
            "hdrp_mask_map_rgba": str(un_dir / f"T_{clean_name}_MaskMap.png"),
            "normal_opengl_pos_y": str(un_dir / f"T_{clean_name}_NormalGL.png"),
        }

    if "godot" in engines or engine == "gltf":
        gd_dir = out_path / "godot"
        gd_dir.mkdir(exist_ok=True)
        sc_gd = _assemble_lod_scene(lod0_mesh, include_colliders="godot")
        gd_glb = gd_dir / f"{clean_name}_godot.glb"
        mk.export_glb_pbr(sc_gd, str(gd_glb), webp=webp)
        exported_profiles["godot"] = {"scene_with_colonly": str(gd_glb)}

    # Planche de contrôle Technical Artist `qa_game_sheet.png` rendue en parallèle sur 4 threads !
    az, el = renderer.DEFAULT_VIEWS["three_quarter"]
    hi_vis = high_body.copy()
    hi_vis.visual.vertex_colors = np.column_stack([
        (np.clip(v_alb, 0.0, 1.0) * 255).astype(np.uint8),
        np.full(len(v_alb), 255, dtype=np.uint8),
    ])
    sc_col_vis = _assemble_lod_scene(lod0_mesh, include_colliders="unreal")
    # v5.5 — les vues face/profil étaient rendues SÉQUEENTIELLEMENT après les 4
    # vues parallèles (~2,6 s de mur). Les 6 rendus passent dans un seul pool :
    # la planche QA est identique, mais le temps mural baisse d'autant.
    _rbx_alb = rbx_col_img if "roblox" in engines else None
    # 2 cœurs en CI : au-delà de 4 threads les rendus se contentionnent (mesuré :
    # 6.8 s à 6 threads contre 6.5 s à 2). ssaa=1.5 au lieu de 2 : −36 % de
    # fragments à l'écran, différence invisible à l'œil sur la planche QA.
    _nw = max(2, min(4, (os.cpu_count() or 2)))
    with ThreadPoolExecutor(max_workers=_nw) as rpool:
        futs = [rpool.submit(renderer.render_view, sc_in, a, e, size=480, ssaa=1.5)
                for sc_in, a, e in [
                    (trimesh.Scene([hi_vis]), az, el),
                    (sc_lod0, az, el),
                    (sc_lod2, az, el),
                    (sc_col_vis, az, el),
                    (sc_lod0, 0.0, 0.0),
                    (sc_lod0, 90.0, 0.0),
                ]]
        im_hi, im_lod0, im_lod2, im_col, im_front, im_side = [f.result() for f in futs]
    draw_c = ImageDraw.Draw(im_col)
    draw_c.rectangle((10, 10, 310, 38), fill=(18, 28, 22))
    draw_c.text((18, 16), f"{len(colliders)} hulls UCX ({sum(len(h.faces) for h in colliders)} tris) + {len(sockets)} sockets", fill=(110, 245, 165))

    im_nrm = baked["normal_gl"].resize((480, 480), Image.BILINEAR)
    im_orm = baked["orm"].resize((480, 480), Image.BILINEAR)

    # Planche QA v2 : vues orthogonales cadrées + barre d'échelle (cm & Studs),
    # carte moteur (ColorMap Roblox à AO cuit) et carte de gates — l'agent ne lit
    # QU'UNE image, elle doit porter les proportions, l'échelle et les métriques.
    ext = np.asarray(high_body.extents, dtype=float)
    studs_xyz = ext * ROBLOX_STUDS_PER_METER
    im_front = _qa_scale_bar(im_front, ext)
    im_side = _qa_scale_bar(im_side, ext)
    if "roblox" in engines:
        im_alb, alb_lbl = rbx_col_img, f"7. T_{clean_name}_ColorMap (AO Roblox cuit)"
    else:
        im_alb, alb_lbl = baked["albedo"], f"7. T_{clean_name}_BC (albédo de-lit)"
    im_card = _qa_metrics_card(clean_name, [
        f"LOD0 {len(lod0_mesh.faces):,} tris | LOD1 {len(lod1_mesh.faces):,} | LOD2 {len(lod2_mesh.faces):,}",
        f"draw calls {raw_draw_calls} -> {final_draw_calls}",
        f"dims {ext[0] * 100:.0f} x {ext[1] * 100:.0f} x {ext[2] * 100:.0f} cm",
        f"Studs {studs_xyz[0]:.2f} x {studs_xyz[1]:.2f} x {studs_xyz[2]:.2f}",
        f"colliders UCX {len(colliders)} ({sum(len(h.faces) for h in colliders)} tris)",
        f"sockets {len(sockets)} | textures {tex_size}² | webp={bool(webp)}",
        f"high-poly {len(high_body.faces):,} tris "
        f"(-{round(100.0 * (1.0 - len(lod0_mesh.faces) / max(len(high_body.faces), 1)))} %)",
    ])

    qa_sheet = out_path / "qa_game_sheet.png"
    renderer.contact_sheet(
        [
            (im_hi, f"1. Source High-Poly ({len(high_body.faces):,} tris, {raw_draw_calls} draw calls)"),
            (im_lod0, f"2. Game LOD0 ({len(lod0_mesh.faces):,} tris, {final_draw_calls} draw calls)"),
            (im_lod2, f"3. Far LOD2 ({len(lod2_mesh.faces):,} tris, bake dédié 128²)"),
            (im_col, f"4. Colliders Physiques UCX ({sum(len(h.faces) for h in colliders)} tris) & Sockets"),
            (im_front, f"5. Face — {ext[0] * 100:.0f} x {ext[2] * 100:.0f} cm | "
                       f"{studs_xyz[0]:.2f} x {studs_xyz[2]:.2f} Studs"),
            (im_side, f"6. Profil — {ext[1] * 100:.0f} x {ext[2] * 100:.0f} cm | "
                      f"{studs_xyz[1]:.2f} x {studs_xyz[2]:.2f} Studs"),
            (im_alb.resize((480, 480), Image.BILINEAR), alb_lbl),
            (im_nrm, "8. Tangent-Space Normal Map (Mikk VEC4)"),
            (im_orm, "9. Packed ORM (R=AO, G=Roughness, B=Metallic)"),
            (im_card, "10. Carte QA & gates"),
        ],
        cols=3,
        out_path=str(qa_sheet),
        title=f"3d-forge v5.5 Game-Ready QA — {clean_name} (High-Poly -> LOD0/1/2 + PBR + Colliders + échelle Studs/cm)",
    )

    manifest = {
        "asset_name": clean_name,
        "lod0_target_tris": int(lod0_tris),
        "high_poly_tris": int(len(high_body.faces)),
        "lods": {
            "LOD0": {"tris": int(len(lod0_mesh.faces)), "path": str(glb_main), "bytes": glb_main.stat().st_size},
            "LOD1": {"tris": int(len(lod1_mesh.faces)), "path": str(glb_lod1), "bytes": glb_lod1.stat().st_size},
            "LOD2": {"tris": int(len(lod2_mesh.faces)), "path": str(glb_lod2), "bytes": glb_lod2.stat().st_size},
        },
        "draw_calls_before": int(raw_draw_calls),
        "draw_calls_after": int(final_draw_calls),
        "poly_reduction_pct": round(100.0 * (1.0 - len(lod0_mesh.faces) / max(len(high_body.faces), 1)), 2),
        "physics_colliders": {
            "count": int(len(colliders)),
            "total_tris": int(sum(len(h.faces) for h in colliders)),
            "path": str(col_glb),
        },
        "joints": joints,
        "sockets": sockets,
        "has_explicit_mikk_tangents": True,
        "webp_compressed": bool(webp),
        "engine_exports": exported_profiles,
        "delight_metrics": baked["delight_metrics"],
        "qa_sheet": str(qa_sheet),
        "duration_s": round(time.perf_counter() - t0, 2),
    }
    (out_path / "game_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    zip_path = pkg.build_asset_zip(out_path, name=clean_name)
    manifest["bundle_zip"] = str(zip_path)
    (out_path / "game_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help="Nom d'une recette catalogue OU chemin vers un fichier .glb/.stl/.obj")
    ap.add_argument("-o", "--out", required=True, help="Dossier de sortie du pack Game-Ready")
    ap.add_argument("--name", default=None, help="Nom de l'asset exporté")
    ap.add_argument("--engine", choices=["roblox_unreal", "roblox", "unreal", "unity", "godot", "gltf", "all"],
                    default="roblox_unreal",
                    help="Profil moteur cible (défaut: roblox_unreal = Roblox Studio + Unreal Engine 5)")
    ap.add_argument("--roblox-scale", choices=["studs", "meters"], default="studs",
                    help="Unité du .glb Roblox Studio : studs (1m = 3.5714 studs, taille R15 directe) ou meters")
    ap.add_argument("--lod0-tris", type=int, default=3400, help="Budget triangles cible pour LOD0")
    ap.add_argument("--tex-size", type=int, default=1024, help="Résolution des textures PBR")
    ap.add_argument("--no-weathering", action="store_true")
    ap.add_argument("--delight", action="store_true", help="Active explicitement le de-lighting SH de l'Albédo")
    ap.add_argument("--no-webp", action="store_true")
    ap.add_argument("--ai-front", default=None, help="Vue orthographique avant peinte sur le GPU Datacenter")
    ap.add_argument("--ai-side", default=None, help="Vue orthographique latérale peinte sur le GPU Datacenter")
    ap.add_argument("--ai-top", default=None, help="Vue orthographique supérieure peinte sur le GPU Datacenter")
    args = ap.parse_args(argv)

    ai_views_cli = {
        k: v for k, v in (("front", args.ai_front), ("side", args.ai_side), ("top", args.ai_top)) if v
    } or None

    if args.source in recipes.REGISTRY:
        import inspect
        mk.set_quality(1.0)
        fn_b = recipes.get(args.source)["builder"]
        b = fn_b(textured=False) if "textured" in inspect.signature(fn_b).parameters else fn_b()
        asset_name = args.name or args.source
        src = b
    else:
        src = Path(args.source)
        asset_name = args.name or src.stem

    manifest = export_game_package(
        src,
        out_dir=args.out,
        name=asset_name,
        engine=args.engine,
        lod0_tris=args.lod0_tris,
        tex_size=args.tex_size,
        weathering=not args.no_weathering,
        delight_pass=True if args.delight else None,
        webp=not args.no_webp,
        roblox_scale=args.roblox_scale,
        ai_views=ai_views_cli,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
