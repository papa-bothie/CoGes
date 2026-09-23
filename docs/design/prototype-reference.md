# Référence visuelle — prototype Bolt CoGes

Source : https://coges-visual-sales-p-ijo3.bolt.host (analysé le 23/09/2026).
Le prototype est une **démo commerciale** (React + Vite + Tailwind + shadcn/ui, données fictives).
Il sert de **référence visuelle et UX** pour le frontend Next.js : on reprend l'apparence, la
navigation et les parcours. On **ne reprend pas** sa logique (tout y est calculé côté client) :
dans CoGes, le front n'a aucune règle métier et affiche ce que renvoie l'API.

## 1. Tokens de couleur (repris tels quels, format HSL shadcn)

```css
:root {
  --background: 210 20% 98%;   --foreground: 215 28% 17%;
  --card: 0 0% 100%;           --card-foreground: 215 28% 17%;
  --popover: 0 0% 100%;        --popover-foreground: 215 28% 17%;
  --primary: 199 89% 28%;      --primary-foreground: 0 0% 100%;   /* bleu pétrole #085F87 */
  --secondary: 210 16% 95%;    --secondary-foreground: 215 28% 17%;
  --muted: 210 16% 93%;        --muted-foreground: 215 16% 47%;
  --accent: 152 63% 40%;       --accent-foreground: 0 0% 100%;    /* vert positif */
  --destructive: 0 72% 51%;    --destructive-foreground: 0 0% 100%;
  --warning: 32 95% 50%;       --warning-foreground: 0 0% 100%;
  --success: 142 71% 45%;      --success-foreground: 0 0% 100%;
  --border: 214 20% 88%;       --input: 214 20% 88%;   --ring: 199 89% 28%;
  --chart-1: 199 89% 28%; --chart-2: 152 63% 40%; --chart-3: 32 95% 50%;
  --chart-4: 0 72% 51%;   --chart-5: 259 84% 56%;
  --radius: .5rem;
}
.dark {
  --background: 215 28% 10%;   --foreground: 210 20% 92%;
  --card: 215 28% 13%;         --card-foreground: 210 20% 92%;
  --popover: 215 28% 13%;      --popover-foreground: 210 20% 92%;
  --primary: 199 89% 48%;      --primary-foreground: 215 28% 10%;
  --secondary: 215 28% 18%;    --secondary-foreground: 210 20% 92%;
  --muted: 215 28% 18%;        --muted-foreground: 215 16% 60%;
  --accent: 152 63% 50%;       --accent-foreground: 215 28% 10%;
  --destructive: 0 72% 55%;    --warning: 32 95% 55%;   --success: 142 71% 50%;
  --border: 215 28% 22%;       --input: 215 28% 22%;    --ring: 199 89% 48%;
  --chart-1: 199 89% 48%; --chart-2: 152 63% 50%; --chart-3: 32 95% 55%;
  --chart-4: 0 72% 55%;   --chart-5: 259 84% 66%;
}
```

Fond de page `#F9FAFB`, texte `#1F2937`, bordures `#DAE0E7`.

## 2. Typographie, formes, ombres

- Police : pile système (`ui-sans-serif, system-ui`). **À améliorer en phase 14** (Impeccable
  `typeset`) : une police lisible avec des chiffres tabulaires pour les montants.
- Titres de page `24px / 700` ; texte courant des tableaux et boutons `14px` ; en-têtes de tableau `14px / 500`.
- Rayons : boutons et champs `6px`, élément de navigation actif `8px`, cartes environ `12px`.
- Ombres légères : `0 1px 3px rgba(0,0,0,.1), 0 1px 2px -1px rgba(0,0,0,.1)` sur les boutons
  primaires, `0 1px 2px rgba(0,0,0,.05)` sur les champs.
- Icônes : jeu de traits fins type **lucide-react**.

## 3. Structure de l'écran

- **Barre latérale fixe** (≈ 208 px, fond blanc, bordure droite) : logo « CoGes » (carré bleu
  pétrole + icône boutique), nom de l'entreprise, puis la navigation : Tableau de bord · Ventes ·
  Stock · Produits · Clients · Fournisseurs · Finance · Analytics · CoGes Intelligence ·
  Paramètres. L'élément actif est rempli en `primary` avec le texte blanc. Version de l'app en pied.
  - ⚠️ Le prototype affiche un **sélecteur d'entreprise** : **à ne pas reprendre**, car
    1 compte = 1 entreprise en V1. On affiche seulement le nom de l'entreprise.
- **En-tête** : titre de la page + nom de l'entreprise en sous-titre à gauche ; à droite, le nom
  de l'utilisateur, son rôle, un avatar (initiale), une cloche de notifications avec un badge rouge
  et un bouton de déconnexion.
- **Contenu** : titre `h1` + compteur (« 20 produit(s) ») à gauche, action principale à droite
  (« + Ajouter un produit », « + Nouvelle vente »). Dessous : barre de recherche + filtres (listes
  déroulantes), puis un tableau dans une carte blanche à bordure fine.
- Le bandeau « Mode démonstration » du prototype n'est **pas** repris en production.

## 4. Composants et motifs à reprendre

| Motif | Où | Détail |
|---|---|---|
| Carte KPI | Tableau de bord | Icône colorée en haut à gauche, libellé en `muted`, valeur en gras. Grille 3 × 2. |
| Bandeau d'alerte cliquable | Tableau de bord | Rouge pâle pour le stock bas, neutre pour une dette échue ; détail à droite + flèche vers l'élément concerné. |
| Graphique en aire | Tableau de bord | CA sur 30 jours, courbe `chart-1`, remplissage dégradé léger, axe Y en « 40 k FCFA ». |
| Liste « Dernières ventes » | Tableau de bord | Référence + client à gauche, montant + date à droite. |
| Tableau de données | Toutes les listes | Colonnes triables, recherche, filtres, montants alignés à droite, lignes cliquables vers le détail. |
| Badge de statut | Ventes, Produits | Brouillon (gris), Confirmée (primary), Annulée (rouge), Retournée (orange) ; Actif, Seuil bas, Rupture. |
| Carte de recommandation | CoGes Intelligence | Icône, badges type + niveau de confiance, titre, lignes **Métrique / Valeur / Date de calcul**, texte explicatif. |
| Compteurs de synthèse | CoGes Intelligence | 4 petites cartes : Risques de rupture, Prévisions de tendance, Anomalies, Données insuffisantes. |

## 5. Défauts du prototype à corriger (ne pas copier)

- Les montants passent sur deux lignes (« 1 000 » puis « FCFA ») dans les colonnes étroites :
  utiliser `white-space: nowrap` et des chiffres tabulaires.
- Le badge « Actif » est rempli en bleu primaire, comme un bouton : les badges de statut doivent
  être plus discrets que les actions.
- Les cartes d'Intelligence sont très hautes et leur texte est long : prévoir une version
  compacte avec le détail dans un panneau latéral.
- La pile de polices système donne des rendus différents selon les systèmes : fixer une police.
- Le sélecteur multi-entreprise et le bandeau démo ne sont pas à reprendre (voir plus haut).

## 6. Écrans de référence à consulter

`/dashboard` · `/sales` · `/sales/new` · `/stock` · `/products` · `/customers` · `/suppliers` ·
`/finance` · `/analytics` · `/intelligence` · `/settings`.
Le prompt Bolt qui a généré le prototype (spécification fonctionnelle écran par écran) est dans
`docs/design/prototype-bolt-prompt.md`.
