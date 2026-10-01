# Audit Impeccable — après finition (phase 14, passe 8)

> Relevé le 01/10/2026 sur `phase/14-polish-impeccable`, mêmes sources que l'audit d'avant
> (`audit-phase-14-avant.md`) : détecteur Impeccable sur `frontend/app` et `frontend/components`,
> axe WCAG 2.1 AA sur 16 écrans + connexion en clair et en sombre
> (`captures/phase-14/apres/a11y-*.json`), captures `captures/phase-14/apres/`, relevés à 1366 × 768,
> 1024 × 768 et 768 × 1024, console du navigateur sur les 16 écrans, lecture du code.

## Note de santé : avant → après

| # | Dimension | Avant | Après | Ce qui a changé |
|---|---|---|---|---|
| 1 | Accessibilité | 2/4 | **3/4** | axe : **218 → 0** violations en clair, **23 → 0** en sombre, y compris en mode strict ; mouvement réduit respecté ; sélecteurs segmentés pilotables au clavier |
| 2 | Performance | 3/4 | **4/4** | plus de `backdrop-blur` ni de `transition-all` ; graphiques sans animation ; police : +25 Ko (axe optique), mise en cache |
| 3 | Adaptation | 2/4 | **3/4** | « Confirmer la vente » toujours visible à 1024 px ; barre latérale repliée sous 1024 px ; colonnes d'appoint ; KPI et Intelligence dans le premier écran à 1366 × 768 |
| 4 | Thème | 3/4 | **4/4** | encres d'état clair et sombre, `*-foreground` complets, survol des menus neutre, aucune couleur en dur |
| 5 | Intégrité | 3/4 | **4/4** | détecteur : **1 → 0** constat ; motifs répétés devenus composants partagés (`SegmentedControl`, `PeriodBarChart`, `spacedGroups`) |
| **Total** | | **13/20** | **18/20** | **Acceptable → Excellent** |

Pourquoi pas 4/4 en accessibilité et en adaptation : la vérification est automatique (axe) et
visuelle ; aucun passage manuel au lecteur d'écran ni au zoom 200 % n'a été fait, et les petits
boutons d'icône (28 px : pagination, croix de fermeture) restent sous les 44 px recommandés au
toucher sur tablette (WCAG 2.2 AA exige 24 px : conforme, mais juste).

## Verdict d'intégrité : **réussi**

Une identité inchangée (bleu pétrole sobre) et désormais **tenue par le système** : rôles
typographiques et encres d'état en tokens, composants partagés pour chaque motif répété, règles
nommées dans `DESIGN.md` (Chiffre aligné, Espace visible, Même chiffre même taille, Sens unique,
Signal unique, Encre, Mouvement réduit). Règles d'affichage métier intactes : métrique nommée,
date de calcul, modèle et version, incertitude, « Données insuffisantes », FCFA sans décimales.

## Les 19 constats de l'audit d'avant

| Constat | Passe | État |
|---|---|---|
| P1-1 Couleurs d'état comme texte | 5 | ✅ encres d'état |
| P1-2 Gris d'annotation sous le seuil | 5 | ✅ 47 % → 42 % |
| P1-3 Cartes d'Intelligence à 75 % d'opacité | 5 | ✅ statut par badge |
| P1-4 Onglets inactifs sous le seuil | 5 | ✅ |
| P1-5 ARIA invalide (filtre des notifications) | 8 | ✅ `SegmentedControl` (radiogroup) |
| P1-6 Pastille de la cloche en sombre | 3, 5 | ✅ 11 px, rouge lisible |
| P1-7 Nouvelle vente à 1024 px | 4 | ✅ barre d'actions fixée en bas |
| P2-1 Indicateurs trop hauts | 4 | ✅ ≈ 110 px, sans pastille d'icône |
| P2-2 Cartes d'Intelligence chargées | 6 | ✅ sans bordure latérale ni répétitions |
| P2-3 Panneau d'Intelligence (débordement, actions) | 4, 6 | ✅ 512 px, action principale |
| P2-4 Sens des couleurs | 5 | ✅ seuil bas orange, un signal par ligne |
| P2-5 Tablette en portrait | 4 | ✅ |
| P2-6 Pas de `prefers-reduced-motion` | 7 | ✅ |
| P2-7 Titre répété dans l'en-tête | 4 | ✅ fil d'Ariane |
| P3-1 `backdrop-blur` | 7 | ✅ retiré |
| P3-2 `transition-all` | 7 | ✅ retiré |
| P3-3 Tailles hors échelle | 3 | ✅ (le reçu imprimé garde les siennes, voulu) |
| P3-4 Échelle non déclarée | 3 | ✅ rôles en tokens |
| P3-5 Courbe lissée | 5 | ✅ barres par période |

## Trouvés et corrigés en route (absents de l'audit d'avant)

- **`cn` supprimait les nouvelles tailles** (prises pour des couleurs) — passe 4.
- **Largeur des panneaux latéraux écrasée** par le composant de base — passe 4.
- **Survol des menus en vert « encaissé »** (jeton `accent`) — passe 5.
- **Séparateur des milliers invisible en grand corps** (« 13000 FCFA ») — passe 6.
- **Croix de fermeture « Close »** en anglais — passe 6.
- **Graduations des graphiques rognées** : « 800 k FCFA » se lisait « 300 k FCFA » (Finance,
  Analytics) — passe 8, axes à largeur automatique.
- **Encours de Finance en orange** alors qu'ils ne sont pas des alertes — passe 8.

## Ce qui reste (reporté)

1. ~~**Textes des notifications composés par le worker**~~ : **traité** après la phase
   (ADR 0057) ; montants, quantités et dates à la française, comme l'écran.
2. ~~**Cibles tactiles de 28 px**~~ (traité, ADR 0059) (`icon-sm` : pagination, croix) : à porter à 36–44 px sur
   tablette.
3. **Passage manuel** au lecteur d'écran (NVDA ou Orca) et au zoom 200 % : non fait.
4. **Champs de date natifs** : leur gabarit dépend de la langue du navigateur (« dd/mm/yyyy » dans
   le Chromium des tests) ; à vérifier sur un navigateur réglé en français.
5. ~~**Bandeau « Dette échue » neutre**~~ (traité, ADR 0059) alors que `DESIGN.md` range « en retard » dans le rouge :
   laissé tel quel (inchangé depuis la phase 13), à trancher.
6. **Commande `delight` non lancée** : hors de la réponse « animations discrètes ».
7. **Deux instabilités e2e en fin de suite longue** (base e2e dédiée, ADR 0059), chacune vue une fois et jamais reproduite
   seule (3 relances vertes chacune) : « session révoquée » (passe 3) et la recherche de la liste
   Produits, filtrée en plus de 5 s quand la base de démo a accumulé les articles des tests
   (passe 8). Hors du périmètre visuel ; à surveiller, voire à purger les données e2e entre deux
   suites.

## Ce qui fonctionne (à garder)

- Montants : `Money` + `numeric` + `spacedGroups`, alignés à droite, jamais coupés.
- Une seule couleur d'action, des états en encre, des fonds teintés discrets.
- Coquille : fil d'Ariane, densité compacte / confortable, barre latérale repliable.
- Aucune erreur ni avertissement dans la console sur les 16 écrans.
- Tests : 96 Vitest, 30 e2e (dont axe en mode strict), sur chaque passe.
