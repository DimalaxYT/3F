# CLAUDE.md — Skill Automatique `3d-forge v5.1 Turbo`

Consulte et applique systématiquement **[`AGENTS.md`](AGENTS.md)** et **[`SKILL.md`](SKILL.md)** pour toute demande de génération, sculpture, texturage PBR ou export 3D (**Roblox Studio** en priorité n°1 + **Unreal Engine 5** en priorité n°2).

### Rappel Express (`< 90 s` par modèle) :
- **1 seule commande tout-en-un (`12–20 s` CPU)** : `python3 scripts/turbo_forge.py <recette | custom_builder.py | --front ... --side ...> -o out/<nom>`
- **Hard-Surface** : combine `scripts/meshkit.py` + les pièces mécaniques 100 % étanches de **`scripts/greebles.py`**.
- **Zéro boucle de 30 minutes** : pas de `research.py fetch` par défaut, pas de `--faces all`, lecture unique de **`out/<nom>/qa_game_sheet.png`**, livraison immédiate si propre (`>= 8.8/10`) ou **1 seule** retouche ciblée maximum.
