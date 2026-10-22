Utilise le skill 3D de ce dépôt GitHub : https://github.com/DimalaxYT/3F
1. Clone le dépôt (s'il n'est pas déjà présent) et installe `requirements.txt` si nécessaire.
2. Lis impérativement `SKILL.md` avant d'écrire une seule ligne de code.
3. RÈGLES ABSOLUES DE FIDÉLITÉ, VITESSE & LIVRAISON ZIP :
   - **ZÉRO `preview.html` / serveur WebGL** : ne génère jamais de page HTML de preview. Tous les livrables (`.glb` LOD0/1/2, `.stl` 100 % étanche, `roblox/`, `unreal/`, planche QA) sont automatiquement empaquetés dans **`exports/<nom>/<nom>.zip`** : **livre toujours ce fichier `<nom>.zip` à l'utilisateur !**
   - **CAS N°1 — L'UTILISATEUR ENVOIE UNE PHOTO / IMAGE (« génère-moi ça à partir de la photo »)** :
     • **INTERDICTION FORMELLE** d'utiliser une recette générique du catalogue (`dragon_creature`, `car`, `hero_bust`…) ou d'inventer des formes/couleurs au hasard !
     • **Étape A (Mesure exacte < 0.5 s)** : lance `python3 scripts/photo_to_3d.py inspect <photo> -o exports/ref --height 0.40`, puis lis `exports/ref/blueprint_grid.png` : récupère le ratio exact `L/H`, les coordonnées métriques `(y, z)` de chaque partie (tête, cou, torse, membres, ailes, queue, accessoires) et la **vraie palette `#RRGGBB` mesurée sur les pixels internes**.
     • **Étape B (Modélisation 3D fidèle 1:1)** : écris `custom_<nom>.py` calé au centimètre près sur les coordonnées `(y, z)` du blueprint :
       - Créatures / organique : `org.Sculpt` (`res >= 76`), **`org.displace_scales`** (vraies écailles 3D gravées dans le maillage, jamais de peau lisse ballon !), **`org.armored_scutes`** (plaques ventrales tangentes ancrées dans le cou/torse, zéro plaque flottante !), **`org.ridge_spines`** (crête dorsale/caudale), **`org.bat_wing`** (ailes solides cambrées à membranes épaisses sans déchirure QEM), griffes/crocs/cornes `org.tapered_curve`.
       - Mécanique / architecture / arme / véhicule : CAO exacte `scripts/meshkit.py` + `scripts/greebles.py`.
     • **Étape C (Forge + Vérification Côte-à-Côte obligatoire)** :
       1. `python3 scripts/turbo_forge.py custom_<nom>.py --lod0-tris 9000 -o exports/<nom>`
       2. `python3 scripts/photo_to_3d.py verify <photo> exports/<nom>/<nom>_game.glb -o exports/<nom>/photo_match.png`
       3. Ouvre `exports/<nom>/photo_match.png` (`[Photo demandée | Modèle 3D généré]`) : si une proportion, posture, aile, queue ou couleur diverge de la photo, corrige les coordonnées une fois, relance `packager.build_asset_zip("exports/<nom>", "<nom>")`, puis **livre `exports/<nom>/<nom>.zip` + `photo_match.png`** !
   - **CAS N°2 — DEMANDE TEXTE SANS PHOTO** :
     • Recette exacte au catalogue SANS photo -> `python3 scripts/turbo_forge.py <recette> -o exports/<nom>`, sinon écris un vrai script `custom_<nom>.py` dédié (`meshkit` + `organic` / `greebles`), vérifie `qa_game_sheet.png`, et **livre `exports/<nom>/<nom>.zip`** !

Objet demandé : [ÉCRIS TON IDÉE OU JOINS TA PHOTO ICI]
