# 0015 — Antidatage des mouvements : fenêtre de 48 heures, en base

- **Date** : 2026-09-23
- **Phase** : 04
- **Statut** : acceptée
- **Décideur** : utilisateur (via `AskUserQuestion`)

## Contexte

Point ouvert **P5**, posé par le § 12.1 point 2 du Modèle de données : « le CMP dépend de l'ordre
des mouvements. Un mouvement inséré avec un `occurred_at` antérieur au dernier mouvement existant
rend le CMP courant différent du CMP recalculé. Le schéma ne l'interdit pas ; c'est inhérent à
toute valorisation en coût moyen. »

Le document laisse explicitement deux options ouvertes, « à trancher avant développement ».

## Options envisagées

1. **Refus au-delà d'une fenêtre de 48 h (retenue)** : le CMP courant ne peut jamais s'écarter du
   CMP recalculé de plus que ce que 48 h de désordre permettent. Recommandation du § 12.1, « plus
   simple à expliquer au gérant ».
2. Refus strict, aucun antidatage : le CMP est exact par construction, mais une réception saisie
   le lendemain matin devient impossible — trop rigide pour une PME qui saisit en fin de journée.
3. Autoriser et corriger chaque nuit par `rebuild_product_stock`, avec trace dans `audit_logs` :
   le CMP affiché peut être faux toute une journée, et le § 5.7 avertit qu'un antidatage produit
   des états intermédiaires négatifs que rien ne détecte au moment de la saisie.

## Décision

La migration 0004 crée `inv_check_backdating()`, trigger **`t05_inv_check_backdating`**
`BEFORE INSERT`, qui refuse tout `occurred_at` antérieur de plus de **48 heures** au dernier
mouvement du même produit, avec le SQLSTATE applicatif **`CG010`** traduit en
`movement_backdated_too_far` (409).

La fenêtre borne le **désordre**, pas l'ancienneté : elle se mesure depuis le dernier mouvement du
produit, jamais depuis `now()`. Un article dormant depuis un mois accepte donc une saisie datée
d'il y a un mois ; un inventaire annuel reste possible.

## Conséquences

- Le préfixe **`t05_`** est significatif : les triggers `BEFORE` se déclenchent dans l'ordre
  alphabétique, et la validation doit précéder `t10_inv_check_reversal` puis `t20_inv_apply` —
  inutile de calculer un CMP qu'on va refuser. C'est le même raisonnement que celui commenté au
  § 8.5 pour `t10_`/`t20_`.
- Le **premier** mouvement d'un produit échappe au contrôle : sans mouvement antérieur, il n'y a
  aucun ordre à perturber. La reprise d'un stock existant peut donc porter n'importe quelle date.
- La fenêtre **admet** un désordre borné. Un mouvement daté d'il y a 24 h inséré après un
  mouvement d'aujourd'hui décale réellement le CMP courant par rapport au CMP recalculé : c'est le
  prix assumé de l'option 1, et c'est exactement ce que `rebuild_product_stock` corrige, en
  adoptant la valeur recalculée, seule cohérente avec le journal (§ 5.7).
- Conséquence sur les tests : **T12** ne peut pas partager une entreprise avec les tests
  d'antidatage. La reconstruction porte sur **toute** l'entreprise, et un article volontairement
  désordonné ailleurs y produirait un écart parfaitement légitime, qui n'apprendrait rien sur la
  formule du CMP. `test_t12_cmp_rebuild.py` crée donc son propre tenant.
- Le contrôle est en base, donc il tient aussi pour les mouvements que Sales écrira en phase 05
  sans passer par le router.
