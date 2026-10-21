# CLAUDE.md — Skill Automatique `3d-forge v5.2`

Consulte et applique systématiquement **[`SKILL.md`](SKILL.md)** (protocole, profils
`turbo/standard/showcase`, arbre de décision, cheatsheet API) et
**[`AGENTS.md`](AGENTS.md)** (séquence d'outils Arena) pour toute demande de
génération, sculpture, texturage PBR ou export 3D (**Roblox Studio** priorité n°1,
**Unreal Engine 5** n°2).

### Rappel Express (`< 90 s` par modèle, profil `turbo`)
- **1 seule commande tout-en-un** : `python3 scripts/turbo_forge.py <recette |
  custom_builder.py | --front ... --side ...> -o out/<nom>` (12–25 s CPU).
- **Hard-surface** : `meshkit.py` + `greebles.py` (jamais de cube nu, jamais
  `meshgen.py` sur du mécanique).
- **QA mesurable, pas au feeling** : gates imprimées au run (`gates.json`,
  `qa_summary.md`, `python3 scripts/gates.py out/<nom> --target hero|ugc|print`) +
  lecture unique de `qa_game_sheet.png`.
- **Zéro boucle infinie** : seuil & budget d'itérations = `python3 scripts/critique.py
  policy` ; pas de `research.py fetch` ni `--faces all` en profil `turbo` ;
  **1 retouche chirurgicale max**.
