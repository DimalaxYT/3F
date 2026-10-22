Utilise le skill 3D de ce dépôt GitHub : https://github.com/DimalaxYT/3F
1. Clone le dépôt (s'il n'est pas déjà présent) et installe `requirements.txt` si nécessaire.
2. Lis impérativement `SKILL.md` avant d'écrire une seule ligne de code.
3. RÈGLES ABSOLUES DE FIDÉLITÉ EXTRÊME AUX DÉTAILS, VITESSE & LIVRAISON ZIP :
   - **ZÉRO `preview.html` / serveur WebGL** : ne génère jamais de page HTML de preview. Tous les livrables (`.glb` LOD0/1/2, `.stl` 100 % étanche, `roblox/`, `unreal/`, planches QA & zoom) sont automatiquement empaquetés dans **`exports/<nom>/<nom>.zip`** : **livre toujours ce fichier `<nom>.zip` à l'utilisateur !**
   - **CAS N°1 — L'UTILISATEUR ENVOIE UNE PHOTO / IMAGE (« génère-moi ça à partir de la photo ») — PROTOCOLE OBLIGATOIRE 4 ÉTAPES (`photo_to_3d.py v2`)** :
     • **INTERDICTION FORMELLE** d'utiliser une recette générique ou d'ignorer les micro-détails (yeux, pupilles, dents, griffes, nervures, écailles, coutures, logos/pochoirs) !
     • **Étape 1 — Inspection métrique + Loupes 3x (`< 0.5 s`)** :
       `python3 scripts/photo_to_3d.py inspect <photo> -o exports/ref --height 0.44`
       Ouvre **impérativement** `exports/ref/blueprint_grid.png` **ET** `exports/ref/zoom_details.png` (loupes 300 % sur la tête/yeux/dents, le torse/pattes et les ailes/accessoires) ainsi que `slice_spans` dans `exports/ref/photo_blueprint.json` !
     • **Étape 2 — Sculpture 3D Multi-Groupes Haute Précision (`UZ(x, u, z)`)** :
       Écris `custom_<nom>.py` mappant directement `(u, z) in [0..1]²` de la photo vers `(Y, Z)` métriques (voir `examples/crimson_dragon/build_crimson_dragon.py`) :
       - Sépare les zones riches en micro-détails via `b.def_joint("head", ...)` / `b.def_joint("wings", ...)` + `b.add(..., group="head")` et exporte avec `gr.export_game_package(..., tex_size=1024, joint_tex_size=1024)` : chaque groupe reçoit son propre atlas `1024²` et son budget de triangles dédié (**zéro dent écrasée**, **zéro œil flou**, **zéro aile déchirée** !) ;
       - Sculpte **tous** les détails anatomiques/mécaniques réels : orbites creusées + globes oculaires + pupilles fendues verticales, 24–32 crocs coniques d'ivoire `#f4eee4` sur fond buccal sombre, narines creusées, cornes/griffes annelées, `org.displace_scales`, `org.armored_scutes`, `org.bat_wing(..., membrane_thickness=0.015)` et `org.ridge_spines` (ou `scripts/greebles.py` en mécanique).
     • **Étape 3 — Transfert PBR Photo Haute Définition Symétrique `360°` sans Halo (`project`)** :
       `python3 scripts/photo_to_3d.py project <photo> exports/<nom> -n <nom> --azimuth 86 --elevation 3.5 --fov 38`
       Projette la **vraie texture photo** + le **micro-relief tangentiel (`Normal` + `ORM`)** sur tous les sous-maillages (`Body` + `joints`) des deux côtés (`360°`), **0 % pixel blanc/fumée**, en préservant `UCX_*` et `Idle_Action` en place !
     • **Étape 4 — Contrôle Microscope 300 % (`verify --zoom`) + `gates.py` + Archive `.zip`** :
       `python3 scripts/photo_to_3d.py verify <photo> exports/<nom>/<nom>_game.glb -o exports/<nom>/photo_match.png --zoom exports/<nom>/photo_details_zoom.png --azimuth 86 --elevation 3.5 --fov 38`
       Inspecte **visuellement** `photo_match.png` ET `photo_details_zoom.png` (vérifie les yeux, les dents, la texture et la silhouette), valide `python3 scripts/gates.py exports/<nom>` (`25/25`), remets à jour `packager.build_asset_zip("exports/<nom>", "<nom>")`, puis **livre `exports/<nom>/<nom>.zip` + les images comparatives** !
   - **CAS N°2 — DEMANDE TEXTE SANS PHOTO** :
     • Recette exacte au catalogue -> `python3 scripts/turbo_forge.py <recette> -o exports/<nom>`, sinon écris un script `custom_<nom>.py` ultra-détaillé (`meshkit` + `organic` / `greebles`), vérifie `qa_game_sheet.png`, et **livre `exports/<nom>/<nom>.zip`** !

Objet demandé : [ÉCRIS TON IDÉE OU JOINS TA PHOTO ICI]
