"""Ce qu'il fallait encore pour que l'argent s'écrive tout seul.

Les tables du § 8.6 et les triggers du § 8.7 sont posés depuis la révision 0006, sous
RLS et avec leurs index (ADR 0019). La phase 07 leur donne enfin des services — et
découvre trois manques, tous validés avant codage.

**1. `idempotency_keys` — point ouvert P4.** La décision 16 de l'architecture exige des
« clés d'idempotence sur les écritures financières », et le Diagramme 5 fait de la
vérification de clé la *première* étape d'un paiement. Le modèle ne porte pourtant ni
table ni colonne pour cela. Une table dédiée, tenant-scoped, plutôt qu'une colonne sur
`payments` : une colonne dirait « ce paiement existe déjà » sans pouvoir **rejouer la
réponse initiale**, et ne couvrirait ni la confirmation de vente ni le remboursement
d'un retour, qui sont aussi des écritures financières.

Plutôt que Redis : l'idempotence est écrite **dans la transaction métier**, comme
l'audit critique et l'outbox. Un rollback annule la clé avec l'écriture, et un Redis
indisponible ne peut pas produire de doublon — même raisonnement que la décision 04.

`UNIQUE (company_id, key)` est à lui seul le mécanisme de concurrence : la seconde
requête bloque sur l'index jusqu'au COMMIT de la première, puis lit la réponse déjà
enregistrée. Aucun verrou applicatif.

**2. `expenses.expense_no`.** L'ADR 0021 a rendu `document_counters` générique et
réservé le préfixe `D` pour les dépenses — mais le § 8.6 ne donne à `expenses` aucune
colonne où ranger le numéro. Sans elle, le compteur et le préfixe déjà livrés restent
morts. Écart assumé, symétrique de `sales.sale_no` et `sale_returns.return_no`.

La colonne est `NOT NULL` sans valeur par défaut : aucun service n'écrit `expenses`
avant cette révision, la table est donc vide. Si elle ne l'était pas, l'`ALTER`
échouerait — c'est le bon comportement, et non un silence.

**3. La permission `debts:write_off`.** Abandonner une créance est une renonciation à
un actif : le gérant seul le fait (ADR 0029). `debts:update`, que le comptable possède,
ne pouvait pas porter ce geste. Le catalogue `permissions` n'a **pas** de RLS — une
migration l'écrit sans détour —, mais son `CHECK` sur `action` énumère sept verbes et
`write_off` n'en fait pas partie : la révision l'ajoute. C'est le rôle de ce `CHECK`
que d'obliger à ce geste explicite plutôt que de laisser le vocabulaire des droits
s'étendre par inadvertance.

Le rattachement aux rôles, lui, vit dans `role_permissions`, qui est en `FORCE ROW
LEVEL SECURITY` : le propriétaire lui-même n'y voit rien. Le backfill lève donc le
`FORCE` le temps de l'`INSERT`, exactement comme le `downgrade` de la révision 0002.
Sans ce backfill, les entreprises créées avant cette révision auraient un gérant
incapable d'abandonner une créance, et rien ne l'aurait signalé.

Aucun trigger, aucun SQLSTATE nouveau : `CG030` et `CG041`-`CG045` couvrent déjà tous
les refus que les paiements et les lettrages peuvent rencontrer (ADR 0026).

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables tenant-scoped créées par cette révision (§ 8.11). T37 les vérifie.
TENANT_TABLES = ("idempotency_keys",)

#: Permission ajoutée au catalogue global, et le rôle système qui la reçoit.
WRITE_OFF_PERMISSION = ("debts:write_off", "debts", "write_off")
MANAGER_ROLE = "gerant"


def _rls(table: str) -> None:
    """Applique le gabarit de politique du projet (ADR 0003) à une table."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE  ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant ON {table}
          USING      (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
          WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
        """
    )


def upgrade() -> None:
    _idempotency_keys()
    _expense_number()
    _write_off_permission()


def downgrade() -> None:
    _drop_write_off_permission()
    _drop_expense_number()
    _drop_idempotency_keys()


# ------------------------------------------------------- 1. clés d'idempotence


def _idempotency_keys() -> None:
    op.execute(
        """
        CREATE TABLE idempotency_keys (
           id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           company_id      uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
           -- Fournie par le client. Bornée : une clé d'un caractère ne distingue
           -- rien, une clé d'un mégaoctet est une arme.
           key             text NOT NULL CHECK (length(btrim(key)) BETWEEN 8 AND 200),
           -- Méthode et chemin, pour qu'une même clé sur deux endpoints différents
           -- soit un abus visible et non un rejeu silencieux.
           endpoint        text NOT NULL,
           request_hash    text NOT NULL,
           -- Nuls entre la réservation et l'enregistrement de la réponse, c'est-à-dire
           -- pendant la transaction seulement : aucun COMMIT ne les laisse nuls.
           response_status integer CHECK (response_status BETWEEN 100 AND 599),
           response_body   jsonb,
           created_at      timestamptz NOT NULL DEFAULT now(),
           expires_at      timestamptz NOT NULL,
           CONSTRAINT idempotency_keys_tenant_uq UNIQUE (company_id, id),
           -- Le coeur du mécanisme : deux requêtes concurrentes s'y sérialisent.
           CONSTRAINT idempotency_keys_key_uq    UNIQUE (company_id, key),
           CONSTRAINT idempotency_keys_lifetime  CHECK (expires_at > created_at)
        )
        """
    )
    # Purge par un job de la phase 08 ; en V1 rien n'est effacé, et une clé
    # conservée trop longtemps n'a jamais rendu une mauvaise réponse.
    op.execute("CREATE INDEX idempotency_expiry ON idempotency_keys (expires_at)")
    for table in TENANT_TABLES:
        _rls(table)


def _drop_idempotency_keys() -> None:
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
    op.execute("DROP TABLE IF EXISTS idempotency_keys")


# ------------------------------------------------------- 2. numéro de dépense


def _expense_number() -> None:
    op.execute(
        """
        ALTER TABLE expenses
          ADD COLUMN expense_no text NOT NULL
              CHECK (length(btrim(expense_no)) > 0)
        """
    )
    op.execute("ALTER TABLE expenses ADD CONSTRAINT expenses_no_uq UNIQUE (company_id, expense_no)")


def _drop_expense_number() -> None:
    op.execute("ALTER TABLE expenses DROP CONSTRAINT IF EXISTS expenses_no_uq")
    op.execute("ALTER TABLE expenses DROP COLUMN IF EXISTS expense_no")


# ------------------------------------------------- 3. permission d'abandon


#: Verbes acceptés par `permissions.action` avant cette révision (§ 8.2).
BASE_ACTIONS = ("read", "create", "update", "delete", "confirm", "cancel", "export")


def _action_check(actions: Sequence[str]) -> None:
    """Réécrit le `CHECK` du vocabulaire des droits."""
    values = ",".join(f"'{action}'" for action in actions)
    op.execute("ALTER TABLE permissions DROP CONSTRAINT IF EXISTS permissions_action_check")
    op.execute(
        f"ALTER TABLE permissions ADD CONSTRAINT permissions_action_check "
        f"CHECK (action IN ({values}))"
    )


def _write_off_permission() -> None:
    code, resource, action = WRITE_OFF_PERMISSION
    _action_check((*BASE_ACTIONS, action))
    op.execute(
        f"INSERT INTO permissions (code, resource, action) "
        f"VALUES ('{code}', '{resource}', '{action}')"
    )
    # `role_permissions` est en FORCE ROW LEVEL SECURITY : sans ce NO FORCE, le
    # propriétaire lui-même ne verrait aucune ligne et l'INSERT … SELECT
    # n'insérerait rien — sans lever d'erreur (ADR 0024). Même procédé que le
    # `downgrade` de la révision 0002.
    op.execute("ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE roles            NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        INSERT INTO role_permissions (company_id, role_id, permission_id)
        SELECT r.company_id, r.id, p.id
          FROM roles r
          CROSS JOIN permissions p
         WHERE r.name = '{MANAGER_ROLE}'
           AND r.is_system
           AND p.code = '{code}'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute("ALTER TABLE roles            FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY")


def _drop_write_off_permission() -> None:
    code, _, _ = WRITE_OFF_PERMISSION
    op.execute("ALTER TABLE role_permissions NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"DELETE FROM role_permissions "
        f"WHERE permission_id IN (SELECT id FROM permissions WHERE code = '{code}')"
    )
    op.execute("ALTER TABLE role_permissions FORCE ROW LEVEL SECURITY")
    op.execute(f"DELETE FROM permissions WHERE code = '{code}'")
    _action_check(BASE_ACTIONS)
