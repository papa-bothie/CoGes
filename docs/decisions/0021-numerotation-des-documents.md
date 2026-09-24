# 0021 — Une suite sans trou par entreprise : `document_counters`

- **Date** : 2026-09-24
- **Phase** : 05
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

`sales.sale_no` est `NOT NULL` et unique par entreprise (`sales_no_uq`), mais le § 8 ne dit ni
comment il est formé, ni qui l'attribue. Le numéro d'une vente engage : un gérant qui présente
ses ventes doit pouvoir montrer une suite continue, et chaque trou est une question à laquelle
il devra répondre.

## Options envisagées

1. **Table compteur verrouillée dans la transaction (retenue)** : `V-000123`, suite continue
   par entreprise. Coût : une ligne de contention par entreprise et par type de document.
2. Séquence PostgreSQL : pas de contention, mais une séquence est un objet **global** — les
   numéros seraient partagés entre entreprises, et un `ROLLBACK` laisserait un trou.
3. Horodatage (`V-20260924-0001`) : pas de compteur central, mais l'unicité reste à garantir
   autrement et la lecture est moins naturelle au comptoir.

## Décision

`document_counters (company_id, document_type) → next_value`, et
`app.core.codes.next_document_number()` qui l'incrémente par un `UPDATE … RETURNING`. Le numéro
est attribué **dès le brouillon**.

## Conséquences

- L'`UPDATE … RETURNING` pose de lui-même le verrou exclusif : deux caisses qui numérotent en
  même temps sont sérialisées, la seconde lit la valeur déjà incrémentée. Aucun doublon, aucun
  trou — **sauf `ROLLBACK`, qui rend le numéro comme il rend la vente**. C'est exactement la
  propriété qu'une séquence PostgreSQL n'a pas.
- La ligne du compteur est créée à la volée (`ON CONFLICT DO NOTHING`) : les entreprises créées
  avant cette phase vendent sans reprise de données.
- **Le numéro est attribué au brouillon**, ce qui le rend identifiable dans une liste et au
  téléphone. Contrepartie assumée : un brouillon abandonné consomme un numéro, et la suite des
  ventes *confirmées* n'est donc pas continue. Ce qui est continu, c'est la suite des
  **documents émis**, ce qui est la question du gérant.
- La table est **générique dès maintenant** : `document_type` accepte `sale`, `sale_return` et
  `expense`. `return_no` (phase 06) et les dépenses (phase 07) n'auront ni migration ni code de
  numérotation à écrire. Les préfixes vivent dans `DOCUMENT_PREFIXES`, côté Python.
- Ce mécanisme ne remplace pas celui des tiers (`CLI-0001`, ADR 0013), qui propose une valeur
  **modifiable** et laisse l'unicité à un index. Un code client se corrige ; un numéro de vente,
  non.
