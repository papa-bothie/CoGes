# 0013 — Codes des tiers et recherche du référentiel

- **Date** : 2026-09-23
- **Phase** : 03
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

`customers.code` et `suppliers.code` sont des colonnes libres du § 8.3, uniques par entreprise
sur les lignes vivantes. Le modèle ne dit pas qui les attribue. Par ailleurs le § 8.10 prévoit
des index GIN trigramme sur les noms sans dire ce que `?search=` doit en faire.

## Décision

**1. Codes attribués par le serveur, modifiables.** Sans `code` dans la requête, le serveur
propose `CLI-0001` / `FRN-0001`, numérotés **par entreprise**. L'appelant peut imposer le sien.

**2. Numérotation calculée, unicité garantie par la base.** Une séquence PostgreSQL est un objet
global : elle donnerait `CLI-0002` au premier client de la deuxième entreprise. Le numéro suivant
vient donc du plus grand compteur du tenant (`max(substring(code from '^CLI-([0-9]+)$'))`), et
l'unicité reste celle de `customers_code_uq`. En cas de création simultanée, l'INSERT perdant
est rejoué sur un SAVEPOINT avec le numéro suivant, cinq fois au plus. L'unicité ne repose
jamais sur le calcul.

**3. Recherche : approximation sur le nom, égalité stricte sur les codes.** `?search=` combine
`name % 'terme'` (similarité trigramme, tolérante aux fautes de frappe) et
`name ILIKE '%terme%'` — les deux servis par l'index GIN du § 8.10, donc sans balayage complet —
plus une **égalité** sur `sku`, `barcode` et `code`. Un code-barres scanné qui ramènerait « le
produit le plus ressemblant » serait une erreur de caisse. Les termes de moins de deux
caractères sont ignorés : ils ne discriminent rien et ne franchissent pas le seuil de similarité.

## Conséquences

- `app/core/codes.py` et `app/core/search.py` portent ces deux mécaniques, partagées par les
  modules du référentiel ; la décision métier (préfixe, ce qui est cherché) reste dans chaque
  module.
- Les codes et les SKU sont mis en **majuscules** à la saisie : les index sont sensibles à la
  casse, et « cli-1 » puis « CLI-1 » désigneraient deux tiers pour un seul code affiché.
- Les lignes supprimées comptent dans la numérotation : réattribuer le code d'un client parti
  brouillerait l'historique des ventes.
