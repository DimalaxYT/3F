# AGENTS.md — Instructions Automatiques pour Agents IA (`3d-forge v5.1 Turbo`)

Ce dépôt contient le moteur et skill **`3d-forge v5.1 Turbo`** permettant de générer des modèles 3D réalistes étanches et texturés PBR `1024²` en **moins de 90 secondes de bout en bout** pour **Roblox Studio (Priorité n°1)**, **Unreal Engine 5 (Priorité n°2)** et l'impression 3D (`.stl`).

Dès que l'utilisateur demande de créer, modifier, texturer ou exporter un objet / arme / prop / véhicule / personnage 3D :

1. **Lis d'abord [`SKILL.md`](SKILL.md)** pour l'API exacte de `scripts/meshkit.py`, `scripts/greebles.py`, `scripts/gpu_sculpt.py`, `scripts/gpu_bridge.py` et `scripts/turbo_forge.py`.
2. **Respecte impérativement le Mode Turbo Express (`< 90 s` au total — ZÉRO BOUCLE DE 30 MIN !)** :
   - **Utilise TOUJOURS `python3 scripts/turbo_forge.py ...` (`12 à 20 s` CPU tout compris)** plutôt que d'enchaîner 10 scripts séparés.
   - **NE LANCE PAS `scripts/research.py fetch`** (scraping web lent) sauf si l'utilisateur fournit des URLs ou demande explicitement une recherche web.
   - **NE LANCE PAS `render_views --faces all`** (14 rendus PNG inutiles) : inspecte **uniquement `qa_game_sheet.png`** généré automatiquement par `turbo_forge.py`.
   - **Zéro boucle infinie (`MAX 1 RETOUCHE`)** : si `qa_game_sheet.png` est propre (`>= 8.8/10`), **livre dès la passe 0** ; sinon fais **au maximum 1 seule correction chirurgicale** puis livre.
   - Si tu utilises `generate_image` (GPU Datacenter) pour des vues multi-angles (`front`, `side`, `top`/`back`), **lance tous les appels `generate_image(..., offer_options=False)` EN PARALLÈLE dans la même réponse**.
3. **Qualité Géométrique & Matériaux `v5.1` non négociable** :
   - **Hard-Surface / Armes / Props / Véhicules** : n'empile jamais de simples boîtes cubiques nues ! Assemble de vrais profils (`mk.loft`, `mk.revolve`, `mk.tube_sweep`) et enrichis systématiquement les surfaces avec **`scripts/greebles.py`** (`hex_bolt`, `bolt_array`, `toggle_latch`, `louver_vent`, `picatinny_rail`, `ribbed_conduit`, `ergonomic_handle`, `corner_armor_cap`).
   - **Organique / Créatures / Bustes** : utilise `turbo_forge.py --front ... --side ... [--back ...]` (`gpu_sculpt.py`).
   - **Roblox Studio (Priorité n°1)** : vérifie toujours que `<Nom>_roblox.glb` est encodé en **PNG pur (`webp=False`)**, à l'échelle **`Studs`**, sous **`< 9 800` triangles par `MeshPart`**, avec AO cuit dans `ColorMap`, parties lumineuses séparées `Neon_*` et script Luau `setup_<Nom>.lua`.
