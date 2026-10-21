# Instructions GitHub Copilot — `3d-forge v5.1 Turbo`

Ce dépôt implémente le moteur 3D procédural et hybride GPU **`3d-forge v5.1 Turbo`** dédié en priorité à **Roblox Studio** (`roblox/<Name>_roblox.glb` en PNG sans perte `webp=False`, échelle `Studs`, `< 9 800 tris/part`, `Neon_*`, `setup_<Name>.lua`) et **Unreal Engine 5** (`unreal/SM_<Name>.glb`, `UCX_*`, `ORM`, normales DirectX `-Y`).

- Réfère-toi toujours à **`AGENTS.md`** et **`SKILL.md`**.
- Passe par l'orchestrateur rapide **`scripts/turbo_forge.py`** (`12–20 s` CPU tout compris) et la bibliothèque mécanique **`scripts/greebles.py`** (`is_watertight == True`).
- Ne lance jamais de boucles de 4–5 reconstructions : inspecte **`qa_game_sheet.png`** et livre en 1 passe (ou max 1 micro-correctif).
