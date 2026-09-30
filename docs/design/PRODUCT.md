# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Gérant** d'une PME ouest-africaine (commerce, boutique, distribution) : pilote l'activité,
  valide les opérations sensibles (annulations, ajustements, abandons de créance), règle les
  paramètres et les utilisateurs.
- **Vendeur** : au comptoir, saisit les ventes vite, souvent avec un client devant lui ; ne voit
  ni les paramètres ni la finance.
- **Comptable** : rapproche paiements, dettes et dépenses, consulte le journal d'activité.

Surtout sur PC portable, parfois sur tablette. Le logiciel est ouvert toute la journée.

## Product Purpose

Logiciel de gestion (pas un ERP) centré sur le cycle **vente → stock → argent → décision** :
vendre, suivre le stock valorisé au CMP, encaisser, suivre dettes et dépenses, puis décider à
l'aide du tableau de bord, des analytics et de CoGes Intelligence. Réussir, c'est qu'un gérant
sache à tout moment ce qu'il a vendu, ce qu'il lui reste, ce qu'on lui doit et ce qu'il doit.

## Positioning

Une gestion pensée pour les PME ouest-africaines : FCFA par défaut, vente à crédit et dettes
clients au cœur du parcours, stock qui ne peut jamais devenir négatif, et des recommandations
d'Intelligence qui nomment toujours leur métrique et disent « données insuffisantes » plutôt que
d'inventer.

## Operating Context

- Boutique ou bureau lumineux, PC d'entrée de gamme, écrans modestes (jusqu'à 1366 × 768).
- Connexion lente ou instable : les chargements et les erreurs réseau sont visibles au quotidien.
- Aisance numérique variable : libellés simples, actions explicites, peu de jargon comptable.
- Documents produits : reçu de vente (ticket 80 mm ou A4), exports CSV / .xlsx.

## Capabilities and Constraints

- Interface en français ; code en anglais. Devise XOF affichée `1 234 567 FCFA` (espace fine
  insécable, sans décimales), dates `jj/mm/aaaa`, heures 24 h, fuseau de l'entreprise.
- Le front n'a aucune règle métier : il affiche ce que renvoie l'API `/api/v1`. Les droits sont
  vérifiés par le serveur ; le front ne fait que masquer.
- Toute recommandation d'Intelligence affiche sa métrique (8 métriques distinctes), sa date de
  calcul, son modèle et sa version, son incertitude ; jamais « meilleur produit ».
- Mode clair et mode sombre.
- Hors V1 : mobile natif, hors ligne, multi-devises, multi-entrepôts.

## Brand Commitments

- Nom : **CoGes**. Identité reprise du prototype : bleu pétrole sobre et rassurant (à raffiner,
  pas à remplacer). Icônes à traits fins (lucide).
- Voix : français clair, factuel, sans familiarité ; messages d'erreur qui disent quoi faire.

## Evidence on Hand

- Jeu de démonstration (`make seed-demo`) : 20 produits, 50 ventes sur 60 jours.
- Référence visuelle du prototype : `docs/design/prototype-reference.md` ; captures des phases
  11 à 14 dans `docs/design/captures/`.
- Aucun témoignage, client nommé ni chiffre d'usage réel : n'en inventer aucun.

## Product Principles

1. **Le chiffre juste d'abord** : un montant ou une quantité se lit sans effort et n'est jamais
   ambigu (unité, signe, date).
2. **Le serveur fait foi** : l'écran montre l'état réel, y compris « en cours », « échec » et
   « données insuffisantes ».
3. **Rapide au comptoir** : la vente se saisit au clavier, sans détour.
4. **Sobre et rassurant** : on gère de l'argent ; la couleur signale un état, jamais une
   décoration.

## Accessibility & Inclusion

WCAG 2.1 AA (vérifié par axe) en clair et en sombre ; contraste renforcé pour les écrans lumineux ;
`prefers-reduced-motion` respecté.
