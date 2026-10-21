# Instructions GitHub Copilot — `3d-forge v5.2`

Ce dépôt implémente le moteur 3D procédural et hybride GPU **`3d-forge`** dédié en
priorité à **Roblox Studio** (`roblox/<Name>_roblox.glb` PNG sans perte, échelle
`Studs`, budget tris par `MeshPart`, `Neon_*`, `setup_<Name>.lua`) et à
**Unreal Engine 5** (`unreal/SM_<Name>.glb`, `UCX_*`, `ORM`, normales DirectX `-Y`).

- Réfère-toi toujours à **`SKILL.md`** (source de vérité : protocoles, profils,
  cheatsheet) et à **`AGENTS.md`** (séquence d'outils agent).
- Passe par l'orchestrateur **`scripts/turbo_forge.py`** (12–25 s CPU tout compris)
  et la bibliothèque mécanique **`scripts/greebles.py`** (`is_watertight == True`).
- La qualité est **mesurée** : `scripts/gates.py out/<nom> --target hero|ugc|print`
  (exit code), `qa_game_sheet.png` (10 panneaux), seuil/budget de critique via
  `scripts/critique.py policy`. Ne lance jamais 4–5 reconstructions : 1 passe,
  1 retouche max.
