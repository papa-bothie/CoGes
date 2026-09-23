# 0015 — Antidatage des mouvements : fenêtre de 48 heures, en base

- **Date** : 2026-09-23
- **Phase** : 04
- **Statut** : acceptée · complétée le 2026-09-23 (borne haute, révision 0005)
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

La migration **0005** complète la même fonction d'une borne haute : `occurred_at` ne peut pas
dépasser `now()` de plus de **5 minutes**, SQLSTATE **`CG011`** traduit en `movement_in_future`
(409). Voir « Correctif » ci-dessous.

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

## Correctif — la fenêtre avait besoin d'une seconde borne (révision 0005)

**Le défaut.** La fenêtre se mesure depuis `max(occurred_at)` du produit. Une date **future**
saisie par erreur — un « 2027 » au lieu de « 2026 » — devient ce maximum. Tout mouvement ultérieur
daté de `now()` tombe alors à plus de 48 h en arrière et se fait refuser en `CG010`, **ventes
comprises**, jusqu'à ce que la date fautive soit atteinte.

**Ce qui rendait le défaut grave.** Le mouvement **inverse**, seule correction possible sur un
journal append-only, est lui aussi daté de `now()` : il était refusé à son tour. Un ajustement
non plus ne passait pas. Le produit devenait irrécupérable par l'API, et seule une intervention
directe en base l'aurait débloqué — précisément ce que le journal append-only existe pour éviter.

**La correction.** La révision 0005 remplace le corps de `inv_check_backdating()` — même trigger,
même nom de fonction — et ajoute la borne haute **avant** le contrôle de la fenêtre : une date
future est une faute de saisie, pas un antidatage, et le message doit le dire. SQLSTATE `CG011`,
code métier `movement_in_future` (409). Le schéma Pydantic porte la même borne, pour que le refus
arrive sans aller-retour avec la base et nomme le champ.

**Sur la tolérance de 5 minutes.** Elle n'est pas de la complaisance : `now()` est évalué par
PostgreSQL, `datetime.now(UTC)` par le serveur d'application, et les deux horloges ne sont pas
parfaitement synchrones. Sans marge, un décalage de quelques secondes ferait échouer une saisie
parfaitement légitime. Aucune saisie honnête n'a besoin de plus de cinq minutes d'avance.

**Pourquoi une révision séparée.** La 0004 était déjà livrable. Une migration livrée ne se
réécrit pas — c'est la règle que le journal qu'elle installe applique à ses propres lignes.
