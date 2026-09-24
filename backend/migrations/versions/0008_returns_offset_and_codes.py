"""La compensation d'une dette, et six refus qui disent enfin leur nom.

Deux écarts au schéma, tous deux validés avant codage (ADR 0024 et 0026).

**1. `pay_method` gagne `offset`.** Le § 4.6 prévoit qu'un retour puisse éteindre une
dette du client « via `payment_allocations` ». Mais une allocation exige un paiement,
et un paiement lié à un retour doit être un `outflow` (`payments_return_outflow`) :
avec les cinq moyens existants, la compensation s'écrirait comme une sortie de caisse
qui n'a pas eu lieu, puis une entrée qui n'a pas eu lieu non plus. La trésorerie du
gérant sortirait fausse des deux côtés.

`offset` n'est pas un sixième moyen de payer : c'est la marque d'une écriture **sans
flux de caisse**. Les deux paiements d'une compensation la portent, et les états de
trésorerie des phases 07 et 08 les excluront sur ce seul critère. Les lettrages, eux,
restent exacts : le retour est remboursé, la dette est réduite.

**2. Six SQLSTATE applicatifs.** Les triggers de retour et de remboursement du § 8.7
sont posés depuis la révision 0006, et inertes jusqu'ici. Ils lèvent leurs refus en
`check_violation` (23514) — déjà porté, dans le périmètre même de la phase, par
`sale_returns_refund_cap`, `sale_return_items_tax_bounds`, `debts_paid_bounds` — ou,
pour trois d'entre eux, sans `ERRCODE` du tout, c'est-à-dire en `P0001`, indistinguable
d'un bug. Un service ne peut pas rendre `refund_exceeds_due` plutôt que 500 sur cette
base.

Même arbitrage qu'aux ADR 0018 et 0023 : **seul l'`ERRCODE` change**. La logique, les
messages et les verrous des quatre fonctions sont restitués mot pour mot.

| SQLSTATE | Fonction                          | Erreur métier               |
|----------|-----------------------------------|-----------------------------|
| `CG040`  | `return_item_check`               | `return_qty_exceeds_sold`   |
| `CG041`  | `refund_check` (reste dû)         | `refund_exceeds_due`        |
| `CG042`  | `refund_check` (sens financier)   | `refund_requires_outflow`   |
| `CG043`  | `refund_check` (sur-affectation)  | `payment_over_allocated`    |
| `CG044`  | `allocation_check` (solde)        | `allocation_exceeds_balance`|
| `CG045`  | `allocation_check` (sur-affectation) | `payment_over_allocated` |

Privilèges : rien à accorder. Aucune table n'est créée, et **aucun DELETE** n'est
concédé — `DELETABLE_TABLES` de T36 reste à quatre tables.

Le `downgrade` rend les quatre fonctions, mais **laisse `offset` dans l'ENUM** : le
retirer supposerait de réécrire `payments.method`, donc soit d'échouer sur une base
qui porte des compensations, soit de les replier sur un moyen de paiement réel — c'est
à dire de falsifier une trésorerie pendant un rollback. Le détail est dans
`_drop_offset_method`.

Pourquoi une révision séparée plutôt qu'une retouche des 0006 et 0007 : une migration
livrée ne se réécrit pas (convention posée par la 0005).

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _add_offset_method()
    _return_triggers(offset_codes=True)
    _allocation_check(offset_codes=True)


def downgrade() -> None:
    """Rend les quatre fonctions trigger à leur état de la révision 0006.

    Le type, lui, garde `offset` : voir `_drop_offset_method`, qui reste appelé pour
    porter cette explication à l'endroit exact où on la cherchera.
    """
    _allocation_check(offset_codes=False)
    _return_triggers(offset_codes=False)
    _drop_offset_method()


# ------------------------------------------------------------- ENUM `pay_method`


def _add_offset_method() -> None:
    """Ajoute `offset` à `pay_method`.

    PostgreSQL 12+ accepte `ADD VALUE` dans une transaction tant que la valeur n'y est
    pas **utilisée** : cette migration ne fait qu'ouvrir le type, elle n'écrit aucune
    ligne. `IF NOT EXISTS` rend l'appel rejouable.
    """
    op.execute("ALTER TYPE pay_method ADD VALUE IF NOT EXISTS 'offset'")


def _drop_offset_method() -> None:
    """Ne retire **pas** `offset`, et explique pourquoi.

    PostgreSQL n'a pas d'`ALTER TYPE … DROP VALUE` : retirer une étiquette impose de
    recréer le type et de convertir `payments.method`, seule colonne qui le porte
    (§ 8.6). Sur une base où des compensations ont été enregistrées, cette conversion
    n'a que deux issues, toutes deux mauvaises :

    * **échouer** — `invalid input value for enum pay_method: "offset"`. Le downgrade
      devient impossible, et avec lui la remise à zéro de `coges_test`, qui passe par
      `downgrade base` à chaque exécution de la suite ;
    * **replier `offset` sur un moyen réel** dans le `USING` — les compensations
      deviendraient des mouvements de caisse qui n'ont jamais eu lieu. La trésorerie
      sortirait fausse d'un downgrade, ce qui est exactement ce que l'ADR 0024
      cherchait à empêcher.

    Supprimer d'abord les lignes concernées n'est pas une option : `payments` est en
    `FORCE ROW LEVEL SECURITY` et `coges_owner` est `NOBYPASSRLS` (ADR 0004). Un
    `DELETE` lancé par une migration n'y verrait **aucune ligne** et n'en supprimerait
    aucune, sans lever d'erreur. Seule une réécriture DDL voit toute la table — d'où
    l'asymétrie qui a fait échouer la première version de ce downgrade.

    L'étiquette reste donc, inerte : à la révision 0007, aucun code ne peut l'écrire
    (`finance.schemas.PaymentMethod` ne la contient pas, `RefundMethod` n'existe pas
    encore), et les compensations déjà enregistrées restent lisibles plutôt que
    détruites ou falsifiées. Ce que ce downgrade **rend** vraiment, c'est l'état des
    quatre fonctions trigger ; c'est là qu'était la substance de la révision.

    `downgrade base` reste un retour complet : la révision 0001 supprime le type.
    """
    # Volontairement vide. `ADD VALUE IF NOT EXISTS` rend le ré-`upgrade` idempotent.


# --------------------------------------------------------- triggers, § 8.7 verbatim


def _return_triggers(*, offset_codes: bool) -> None:
    """`return_item_check` et `refund_check`, au mot près, au code d'erreur près.

    `offset_codes=False` restitue exactement les corps de la révision 0006 : un
    downgrade rétablit un état, il ne le corrige pas.
    """
    qty_cap = "'CG040'" if offset_codes else "'check_violation'"
    over_refund = "'CG041'" if offset_codes else "'check_violation'"
    # Ces deux-là n'avaient aucun ERRCODE en 0006 : ils remontaient en `P0001`.
    wrong_way = " USING ERRCODE = 'CG042'" if offset_codes else ""
    over_paid = " USING ERRCODE = 'CG043'" if offset_codes else ""

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION return_item_check() RETURNS trigger AS $$
        DECLARE v_sold numeric(14,3); v_already numeric(14,3);
        BEGIN
           SELECT qty INTO v_sold FROM sale_items
            WHERE company_id = NEW.company_id AND id = NEW.sale_item_id FOR UPDATE;
           IF NOT FOUND THEN RAISE EXCEPTION 'Ligne de vente introuvable'; END IF;
           SELECT COALESCE(SUM(qty), 0) INTO v_already FROM sale_return_items
            WHERE company_id = NEW.company_id AND sale_item_id = NEW.sale_item_id
              AND id <> NEW.id;
           IF v_already + NEW.qty > v_sold THEN
              RAISE EXCEPTION 'Retour cumule % superieur a la quantite vendue %',
                 v_already + NEW.qty, v_sold USING ERRCODE = {qty_cap};
           END IF;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION refund_check() RETURNS trigger AS $$
        DECLARE v_due numeric(14,2); v_free numeric(14,2); v_dir cash_direction;
        BEGIN
           SELECT total_refund - refunded_total INTO v_due FROM sale_returns
            WHERE company_id = NEW.company_id AND id = NEW.sale_return_id FOR UPDATE;
           IF NOT FOUND THEN RAISE EXCEPTION 'Retour introuvable'; END IF;
           IF NEW.amount > v_due THEN
              RAISE EXCEPTION 'Remboursement % superieur au reste du %', NEW.amount, v_due
                 USING ERRCODE = {over_refund};
           END IF;
           SELECT direction, amount - COALESCE(
                     (SELECT SUM(r.amount) FROM sale_return_refunds r
                       WHERE r.payment_id = p.id AND r.id <> NEW.id), 0)
             INTO v_dir, v_free
             FROM payments p
            WHERE p.company_id = NEW.company_id AND p.id = NEW.payment_id FOR UPDATE;
           IF v_dir <> 'outflow' THEN
              RAISE EXCEPTION 'Un remboursement de retour exige direction = outflow'{wrong_way};
           END IF;
           IF NEW.amount > v_free THEN
              RAISE EXCEPTION 'Paiement sur-affecte : reste % disponible', v_free{over_paid};
           END IF;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )


def _allocation_check(*, offset_codes: bool) -> None:
    """`allocation_check`, au mot près, au code d'erreur près.

    La compensation d'une dette passe par une allocation : ses deux refus doivent être
    nommables au même titre que ceux du remboursement.
    """
    over_balance = "'CG044'" if offset_codes else "'check_violation'"
    over_paid = " USING ERRCODE = 'CG045'" if offset_codes else ""

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION allocation_check() RETURNS trigger AS $$
        DECLARE v_bal numeric(14,2); v_free numeric(14,2);
        BEGIN
           SELECT balance INTO v_bal FROM debts
            WHERE company_id = NEW.company_id AND id = NEW.debt_id FOR UPDATE;
           IF NEW.amount > v_bal THEN
              RAISE EXCEPTION 'Affectation % superieure au solde restant %',
                 NEW.amount, v_bal USING ERRCODE = {over_balance};
           END IF;
           SELECT p.amount - COALESCE((SELECT SUM(a.amount) FROM payment_allocations a
                                        WHERE a.payment_id = p.id AND a.id <> NEW.id), 0)
             INTO v_free FROM payments p
            WHERE p.company_id = NEW.company_id AND p.id = NEW.payment_id FOR UPDATE;
           IF NEW.amount > v_free THEN
              RAISE EXCEPTION 'Paiement sur-affecte : reste % disponible', v_free{over_paid};
           END IF;
           RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
