# AUTOCRITIQUE NOTÉE — le prompt de la boucle qualité

Ce fichier EST le prompt. Un agent qui génère avec 3d-forge l'exécute tel
quel, après chaque génération, avant toute livraison. Le moteur déterministe
qui structure la boucle est `scripts/critique.py` (fiche, verdict, historique).

---

## LE PROMPT (à copier tel quel dans ton contexte d'agent)

```text
Tu es ton propre contrôleur qualité. Après CHAQUE génération 3D, avant de
livrer quoi que ce soit :

1. RÉGENÈRE la fiche de critique de l'itération courante :
   python3 scripts/critique.py brief --dir out/<objet> --iter <N>
2. OUVRE et REGARDE chaque photo listée dans la fiche (les 6 faces, le
   turntable, les vues de contrôle, la planche des références). Une note
   donnée sans avoir lu les photos est une triche.
3. NOTE le résultat sur 10 avec le barème :
     S  silhouette & proportions   /3   (IoU multi-vues + lecture des photos)
     V  volume inter-faces         /2   (face/dos/gauche = même objet)
     M  matériaux & textures       /2   (overlays visibles et stables)
     D  détails à respecter        /2   (checklist Stage 0, -0.5 par détail absent)
     T  technique                  /1   (watertight, budget, dégénérés)
   Chaque point perdu DOIT correspondre à une issue concrète et localisée
   (format : AXE|problème observé|correctif proposé). Une note de
   complaisance est une triche : si tu doutes, la note descend.
4. ENREGISTRE ton verdict :
   python3 scripts/critique.py verdict --dir out/<objet> --iter <N> \
       --note <N> --justification "..." --issue "S|..." --issue "D|..."
5. DÉCISION, sans exception :
   - note < 9.5  ->  tu n'as PAS le droit de livrer. Continue à paufiner :
     applique tes correctifs au spec, régénère dans out/<objet>/iter_<N+1>,
     re-critique. Répéte jusqu'à 9.5+ (ou budget d'itérations épuisé).
   - note >= 9.5  ->  relance le verdict avec --deliver, et SEULEMENT
     maintenant tu envoies le résultat à l'utilisateur.
6. À la fin du budget d'itérations (défaut 4), le code force une livraison
   honnête (FORCE_DELIVER) : les issues résiduelles restent documentées dans
   critique_log.json et sont annoncées à l'utilisateur. Jamais de faux 9.5.

Le code te protège contre toi-même : un 9.5+ avec des issues ouvertes est
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
- **Le seuil 9.5 est volontairement exigeant** : il force en pratique 2-3
  itérations — exactement comme Meshy, qui re-verifie la cohérence de ses
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
            note < 9.5  -> corrige le spec -> retour Stage 2 (iter_2, iter_3…)
            note >= 9.5 -> verdict --deliver -> LIVRAISON
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
