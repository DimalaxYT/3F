Utilise le skill 3D de ce dépôt GitHub : https://github.com/DimalaxYT/3F
1. Clone le dépôt (s'il n'est pas déjà présent) et installe `requirements.txt` si nécessaire.
2. Lis impérativement `SKILL.md` et `AUTOCRITIQUE.md` avant d'écrire une seule ligne de code.
3. RÈGLES D'OR QUALITÉ & VITESSE (`< 60 s` au total — ZÉRO BOUCLE INFINIE D'UNE HEURE !) :
   - **ZÉRO dessin 2D synthétique (`PIL` / `matplotlib`)** dans `--front` / `--side` !
   - **ZÉRO « soupe de primitives » brutes** (`sphere` + saucisse + pilules jaunes) sur de l'organique !
   - Choisis la bonne brique `3d-forge` :
     • **Recette proche au catalogue** (`hero_bust`, `tengu_mask`, `stylized_character`, `dragon_creature`, `katana`, `sci_fi_crate`, `car`… — 24 recettes dans `references/recipes.md`) -> utilise-la ou adapte `scripts/recipes/characters.py` !
     • **Personnage, buste, masque (Tengu/Oni/casque), mascotte ou créature sur mesure** -> sculpte en vraie argile 3D SDF continue **`org.Sculpt`** (`s.ellipsoid`, `s.capsule`, **`s.sweep`** pour nez/arcades/pommettes/plis/orbites) + **`b.trim_inside(inner_cutter)`** sur tout masque/casque creux pour qu'aucun œil/croc/bouche ne dépasse JAMAIS à l'arrière + matériaux nobles (`mk.mat.lacquer`, `skin`, `enamel`, `metal`, `clay`).
     • **Objet mécanique / arme / véhicule / meuble** -> CAO exacte `scripts/meshkit.py` + `scripts/greebles.py`.
   - **UNE SEULE commande d'orchestration** : `python3 scripts/turbo_forge.py <recette | custom.py> -o out/<nom>` (~15 s CPU : High-Poly -> `LOD0/1/2` 1 draw call + Roblox PNG Studs + UE5 ORM DirectX `-Y` + `.stl` 100 % étanche + `preview.html` WebGL + `qa_game_sheet.png` + `25/25` gates).
   - **MAX 1 RETOUCHE** : ouvre uniquement `out/<nom>/qa_game_sheet.png` avec `read_file`. Si tout est propre et `25/25 OK`, livre immédiatement sans relancer 5 ou 10 fois !

Objet demandé : [ÉCRIS TON IDÉE ICI — ex: un masque de Tengu japonais en bois laqué rouge et or avec son cordon, prêt pour Roblox Studio, UE5 et l'impression 3D]
