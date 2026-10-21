# AUTOCRITIQUE NOTÉE — Protocole Turbo Express (`< 90 s` bout en bout, `v5.1 Turbo`)

Ce fichier EST le prompt. Un agent qui génère avec `3d-forge` l'exécute tel
quel après `turbo_forge.py`, **sans jamais partir dans des boucles de 30 minutes**.
Le moteur déterministe qui structure le contrôle est `scripts/critique.py` (`THRESHOLD = 8.8`, `MAX_ITERS = 1`).

---

## LE PROMPT TURBO EXPRESS (à suivre strictement)

```text
Tu es ton propre contrôleur qualité — RAPIDE et EXIGEANT (< 90 s au total) :

1. GÉNÈRE EN UNE SEULE COMMANDE via `scripts/turbo_forge.py` (12 à 20 s CPU tout compris :
   géométrie + LOD0/1/2 + pack `roblox/` PNG Studs + pack `unreal/` ORM + `qa_game_sheet.png`).
   Ne lance PAS `render_views --faces all` (14 images inutiles) ni `research.py fetch`.
2. OUVRE UNIQUEMENT `qa_game_sheet.png` avec `read_file` (les 4 vues de contrôle réunies en
   une seule planche). Une note donnée sans avoir lu `qa_game_sheet.png` est une triche.
3. NOTE le résultat sur 10 avec le barème 6 axes :
     S  silhouette & proportions   /2.5 (proportions réalistes sur les 4 angles)
     V  volume, CAO & sculpture    /1.5 (CAO/greebles nettes sur mécanique, `gpu_sculpt.py` lisse sur organique)
     M  matériaux, verre & vernis  /1.5 (PBR sémantique : caoutchouc `metallic=0`, acier/émail nets)
     R  photoréalisme visuel       /1.5 (AO creux dans `ColorMap` Roblox, reliefs Mikk normal, Z-buffer propre)
     D  détails & articulations    /2.0 (boulons, évents, poignées, sockets, pivots `def_joint`)
     T  technique & moteurs        /1.0 (`is_watertight == True`, Roblox `< 9 800 tris/part` & `PNG` pur)
4. DÉCISION IMMÉDIATE (ZÉRO BOUCLE INFINIE — `MAX_ITERS = 1`) :
   - note >= 8.8 (ou >= 8.5 avec `--fast`) -> LIVRE IMMÉDIATEMENT DÈS LA PASSE 0 (`0` rebuild inutile !).
   - note < 8.8 -> applique UNE SEULE retouche chirurgicale ciblée (`iter_1`), vérifie `qa_game_sheet.png`,
     et LIVRE DIRECTEMENT (`FORCE_DELIVER` à `iter_1`). Ne reconstruis JAMAIS 4 ou 5 fois !
```

Le code te protège contre la complaisance tout en garantissant une génération **15× à 20× plus rapide** : un verdict >= seuil avec des issues ouvertes est
rejeté, une note basse sans diagnostic est rejetée, un IoU < 0.5 interdit
un 9.5+. Ne cherche pas à le contourner — c'est ça, la qualité.
```

---

## Pourquoi ce fonctionnement

- **Une note sans barème ne vaut rien.** Le barème S/V/M/D/T transforme « j'aime
  bien » en décompte vérifiable ; chaque point perdu pointe un correctif.
- **Le code garde l'historique** (`critique_log.json`) : notes par itération,
  issues, correctifs, métriques. La tendance (`status`) montre si tu progresses
  ou si tu tournes en rond.
- **Le seuil (`critique.py policy`) est volontairement exigeant** : il force en
  pratique 1-2 itérations — exactement comme Meshy, qui re-verifie la cohérence de ses
  textures multi-vues avant d'afficher le preview. La note est bornée
  mécaniquement (T technique, IoU) : une boucle saine termine typiquement
  en FORCE_DELIVER entre 8.5 et 9.2 — c'est le dénouement normal, pas un
  échec. `critique_log.json` trace `best_note`, qui reste le score de
  référence de l'objet.
- **La livraison forcée est honnête** : au bout du budget, on livre avec la
  note atteinte et les issues résiduelles écrites, jamais un 10 imaginaire.

## Intégration dans le workflow

```
Stage 0  recherche web (research.py)          -> references/ (détails à respecter)
Stage 1  spec JSON (vues ASCII + palette)     -> spec v1
Stage 2  meshgen.py --faces all --references  -> iter_1/ (mesh + photos)
Stage 3  AUTOCRITIQUE (ce prompt)             -> critique.py brief/verdict
            note < seuil   -> corrige le spec -> retour Stage 2 (iter_2, …)
            note >= seuil  -> verdict --deliver -> LIVRAISON
```

Exemple de boucle réelle (épée médiévale rouillée, pommeau en or) :

```
iter_1 : 7.2  [S] pointe trop fine mangée par le lissage   -> res 80->96, smooth 10->7
              [D] fuller invisible de profil               -> peindre le fuller dans side aussi
iter_2 : 8.6  [M] rouille absente du dos de la lame        -> band [0.10, 0.72], coverage 0.42->0.5
              [V] garde trop plate vue de profil           -> side : 3 lignes -> 4
iter_3 : 9.6  --deliver -> LIVRAISON (log complet conservé)
```

## Workflow D — autocritique par partie ET sur l'assemblage

Pour les générations multi-parties (`assemble.py`), la boucle notée s'applique
à DEUX niveaux :

1. **Par partie** : chaque partie a son dossier `out/<objet>/parts/<id>/`
   (rendus + report.json). Quand l'IoU d'une partie est le point faible du
   barème S, ouvre SES rendus, diagnostique, corrige SA spec, puis régénère
   uniquement cette partie :
   `python3 scripts/assemble.py manifest.json --out out/<objet> --part <id>`
   (les autres parties viennent du cache — itérer est rapide).
2. **Sur l'assemblage** : photos des 6 faces + turntable de l'objet complet,
   checklist des détails Stage 0, et vérifications propres au D :
   - les parties sont-elles ALIGNÉES (axes coaxiaux, pas de flottement) ;
   - les CHEVAUCHEMENTS sont-ils invisibles sur les photos ;
   - l'union STL est-elle étanche (`report.validation.watertight_union`) ;
   - les textures changent-elles proprement d'une partie à l'autre (pas de
     glissement de matériau à la jonction).

Le barème S (silhouette) s'évalue sur l'assemblage entier ; un défaut localisé
à une seule partie doit apparaître comme issue `S|...` pointant cette partie.
