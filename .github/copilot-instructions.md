# Instructions GitHub Copilot — `3d-forge v5.8`

Ce dépôt implémente le moteur 3D procédural CAO, **Sculpture SDF Organique (`scripts/organic.py`)**, **Reconstruction Fidèle Photo → 3D (`scripts/photo_to_3d.py`)** et hybride GPU **`3d-forge`** dédié en priorité à **Roblox Studio** (`roblox/<Name>_roblox.glb` PNG sans perte, échelle `Studs`, budget tris par `MeshPart`, `Neon_*`, `setup_<Name>.lua`), **Unreal Engine 5** (`unreal/SM_<Name>.glb`, `UCX_*`, `ORM`, normales DirectX `-Y`), et l'**impression 3D étanche**, livré automatiquement sous forme d'archive **`<name>.zip`** (`scripts/packager.py`, zéro `preview.html`).

- Réfère-toi toujours à **`SKILL.md`** (source de vérité : protocoles, cheatsheet hard-surface + organique, profils) et à **`AGENTS.md`**.
- **Zéro image 2D `PIL`/`matplotlib` dans `--front`/`--side`** : pour tout personnage, buste, mascotte ou créature sur CPU, utilise **`scripts/organic.py` + `scripts/meshkit.py`** (exemples de référence dans **`scripts/recipes/characters.py`**) ; pour le mécanique, **`scripts/meshkit.py` + `scripts/greebles.py`**.
- Passe par l'orchestrateur **`scripts/turbo_forge.py`** (11–18 s CPU tout compris) et vérifie systématiquement **`scripts/gates.py out/<nom> --target hero|ugc|print`** + **`qa_game_sheet.png`**.
