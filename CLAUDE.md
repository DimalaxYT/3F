# CLAUDE.md — Point d'entrée Agent IA (`3d-forge v5.8`)

Bienvenue dans le dépôt **`3d-forge`**. Si un utilisateur te demande de générer, modéliser, sculpter, corriger ou exporter un modèle 3D (personnage, buste, Mario, créature, arme, véhicule, prop Roblox Studio, asset Unreal Engine 5 ou fichier imprimable 3D) :

1. **Lis immédiatement [`SKILL.md`](SKILL.md)** en intégralité — c'est ta source de vérité opérationnelle (cheatsheet exacte `meshkit.py` + `organic.py` + `greebles.py`, profils `turbo|standard|showcase`, contrat de vitesse et QA).
2. **INTERDICTION ABSOLUE DES DESSINS 2D `PIL` POUR `--front`/`--side`** :
   - Sur **Claude.ai** ou tout environnement sans vrai modèle de diffusion d'images photoréalistes (`generate_image`), **NE DESSINE JAMAIS** de PNG 2D synthétiques avec `PIL.ImageDraw` / `matplotlib` pour les donner à `gpu_sculpt.py` ou `turbo_forge.py --front` ! Cela extrude des ellipses baveuses aux couleurs brûlées.
   - Pour **TOUT personnage, buste (ex: Mario, héros, mascotte), animal ou créature sur CPU/Claude.ai** : utilise une recette existante (`hero_bust`, `stylized_character`, `dragon_creature` — voir **`scripts/recipes/characters.py`**) **OU** écris un script `custom_<nom>.py` avec **`meshkit.py` + `organic.py`** (`org.Sculpt`, `org.add_stylized_eyes`, `org.tapered_curve`, `org.curved_visor`, `org.museum_plinth`, matériaux nets `mk.mat.skin` / `enamel` / `clay` / `denim`) !
   - N'utilise `--front f.png --side s.png` **que** si de vraies vues orthographiques photoréalistes existent ou viennent d'être générées par `generate_image(offer_options=False)`.
3. **Passe toujours par l'orchestrateur unifié `scripts/turbo_forge.py`** (`11–18 s` CPU tout compris) :
   - `python3 scripts/turbo_forge.py <recette | custom_<nom>.py> -o out/<nom>`
4. **Inspection visuelle obligatoire avant livraison** :
   - Ouvre `out/<nom>/qa_game_sheet.png` avec `read_file` et inspecte **la vue de face (panneau 5), le profil (panneau 6), le 3/4 LOD0 (panneau 2), l'ORM (panneau 9) et `gates.json`** (`25/25 OK`).
   - Vérifie qu'aucun badge/bouton/œil n'est enterré sous une surface voisine et que les couleurs sont vives, nettes et harmonieuses. Fais **1 retouche ciblée max** si nécessaire, puis présente `out/<nom>/preview.html` à l'utilisateur.
