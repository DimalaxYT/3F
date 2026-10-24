# Preview temps réel — G36E

Visualiseur WebGL autonome : **three.js vendorisé**, aucun CDN, aucune requête
externe. La page ne charge que des URL relatives, donc elle passe derrière
n'importe quel proxy (y compris l'aperçu de la sandbox).

```bash
# 1. générer le modèle (une fois)
python3 scripts/turbo_forge.py g36 -o exports/g36

# 2. servir
python3 preview/serve_preview.py --port 8000
#    -> http://localhost:8000
```

Le serveur sert la **racine du dépôt** (le GLB vit dans `exports/`, ignoré par
git) et répond directement sur `/` — pas de redirection, pour rester compatible
avec les proxys qui ne réécrivent pas les chemins.

> **Toutes les références de la page sont des chemins absolus** (`/preview/…`,
> `/exports/…`). C'est obligatoire : la page est servie sur `/`, donc une
> référence relative comme `href="style.css"` serait demandée à `/style.css` et
> renverrait 404 — page blanche sans style ni script. Une balise
> `<base href="/preview/">` double la sécurité.
>
> Un diagnostic embarqué (script classique, indépendant des modules) affiche un
> bandeau rouge au bout de 4 s si la feuille de style ou le module n'ont pas
> démarré, avec la liste des URL à contrôler.

## Ce que fait la page

| Fonction | Détail |
|---|---|
| Orbite / zoom | `OrbitControls`, rotation automatique désactivable |
| Vues | 3/4, Profil, Dessus, Face, Arrière — aussi `1`…`5`, `R` pour réinitialiser |
| LOD | bascule LOD0 / LOD1 / LOD2 en direct (fichiers GLB séparés) |
| Arêtes franches | `EdgesGeometry` à 24° : montre les chanfreins de 2,2 mm |
| Filaire | bascule `wireframe` sur les matériaux |
| Sockets | points issus de `game_manifest.json`, colorés par usage |
| Colliders UCX | hulls affichés en fil de fer rouge |
| Sol & grille | grille 2,4 m + disque d'ombre |
| Comparaison photo | caméra **orthographique** calée sur la boîte englobante + photo de référence recadrée sur son masque, superposition au pixel (opacité + séparateur glissant) |

## Pourquoi le mode comparaison est fiable

La caméra orthographique a un frustum **exactement égal** à la boîte englobante
du modèle : la silhouette touche les quatre bords du canvas (vérifié, les
extrêmes se projettent en NDC ±1,000) et le canon pointe à gauche, comme sur la
photo. L'image de référence est recadrée sur son propre masque, donc elle couvre
le même rectangle. Les deux se superposent sans réglage.

C'est ce qui permet de juger la **ressemblance** — ce que les gates ne mesurent
pas (24/24 sur un modèle que l'utilisateur a jugé raté).
