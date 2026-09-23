"""Harnais de fuite inter-tenant, réutilisable par toutes les phases.

Deux entreprises **A** et **B** sont créées avec leurs propres données, puis chaque
phase ajoute ses tables à `TENANT_TABLES` et ses fabriques ici. Les tests croisés
(A → A autorisé, A → B vide, B → A vide, écriture croisée refusée) s'appliquent
alors automatiquement aux nouvelles tables.

Amorçage d'un tenant : l'UUID de l'entreprise est **généré côté serveur avant**
l'INSERT, puis posé comme contexte. La politique `companies_self` accepte alors
l'écriture (`WITH CHECK id = current_setting(...)`), sans aucun contournement de la
RLS ni fonction `SECURITY DEFINER`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.security import hash_password
from app.core.tenancy import TenantContext, tenant_transaction

# Tables tenant-scoped couvertes par les tests croisés.
# Chaque phase ajoute les siennes ; T37 vérifie en plus, génériquement, qu'aucune
# table portant `company_id` n'échappe à la RLS.
TENANT_TABLES: tuple[str, ...] = (
    "users",
    "roles",
    "user_roles",
    "role_permissions",
    "auth_sessions",
    "business_events",
)

# Valeur factice : aucun mot de passe réel ne figure dans les tests.
PLACEHOLDER_PASSWORD_HASH = "argon2-placeholder-not-a-real-hash"  # noqa: S105


@dataclass(frozen=True, slots=True)
class Tenant:
    """Une entreprise de test et ses identifiants."""

    slug: str
    company_id: UUID
    user_id: UUID
    role_id: UUID
    permission_id: UUID
    email: str

    @property
    def ctx(self) -> TenantContext:
        """Contexte applicatif de cette entreprise."""
        return TenantContext(user_id=self.user_id, company_id=self.company_id)


def catalogue_permission_id(owner_engine: Engine, code: str = "dashboard:read") -> UUID:
    """Identifiant d'une permission du catalogue global, livré par la migration 0002.

    Lu avec le rôle **propriétaire** : `coges_app` n'a que SELECT sur ce catalogue
    (ADR 0004), et le vocabulaire des droits n'est jamais écrit par un tenant.
    """
    with owner_engine.begin() as connection:
        return UUID(
            str(
                connection.execute(
                    text("SELECT id FROM permissions WHERE code = :code"), {"code": code}
                ).scalar_one()
            )
        )


def create_tenant(
    session_factory: sessionmaker[Any],
    owner_engine: Engine,
    slug: str,
    *,
    password: str | None = None,
) -> Tenant:
    """Crée une entreprise complète : société, utilisateur, rôle, rattachement."""
    company_id = uuid4()
    user_id = uuid4()
    role_id = uuid4()
    # `.test` est un domaine réservé que le validateur d'e-mail refuse : les comptes
    # de test utilisent donc un sous-domaine d'example.com.
    email = f"gerant@{slug}.example.com"
    password_hash = hash_password(password) if password else PLACEHOLDER_PASSWORD_HASH

    # Le contexte est posé sur l'UUID pré-généré : l'INSERT satisfait `WITH CHECK`.
    bootstrap = TenantContext(user_id=user_id, company_id=company_id)

    with tenant_transaction(bootstrap, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO companies (id, name, slug, currency, timezone) "
                "VALUES (:id, :name, :slug, 'XOF', 'Africa/Dakar')"
            ),
            {"id": company_id, "name": f"Entreprise {slug.upper()}", "slug": slug},
        )
        session.execute(
            text(
                "INSERT INTO users (id, company_id, email, password_hash, full_name) "
                "VALUES (:id, :company_id, :email, :password_hash, :full_name)"
            ),
            {
                "id": user_id,
                "company_id": company_id,
                "email": email,
                "password_hash": password_hash,
                "full_name": f"Gérant {slug.upper()}",
            },
        )
        session.execute(
            text("INSERT INTO roles (id, company_id, name) VALUES (:id, :company_id, :name)"),
            {"id": role_id, "company_id": company_id, "name": "gerant"},
        )
        session.execute(
            text(
                "INSERT INTO user_roles (user_id, role_id, company_id) "
                "VALUES (:user_id, :role_id, :company_id)"
            ),
            {"user_id": user_id, "role_id": role_id, "company_id": company_id},
        )

    permission_id = catalogue_permission_id(owner_engine)
    tenant = Tenant(
        slug=slug,
        company_id=company_id,
        user_id=user_id,
        role_id=role_id,
        permission_id=permission_id,
        email=email,
    )

    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id, company_id) "
                "VALUES (:role_id, :permission_id, :company_id)"
            ),
            {"role_id": role_id, "permission_id": permission_id, "company_id": company_id},
        )

    # Une ligne dans chaque table tenant-scoped de la phase 02, pour que les tests
    # croisés portent sur des données réelles et non sur des tables vides.
    with tenant_transaction(tenant.ctx, session_factory=session_factory) as session:
        session.execute(
            text(
                "INSERT INTO auth_sessions "
                "(company_id, user_id, token_hash, family_id, expires_at) "
                "VALUES (:company_id, :user_id, :token_hash, gen_random_uuid(), "
                "now() + interval '7 days')"
            ),
            {
                "company_id": company_id,
                "user_id": user_id,
                "token_hash": f"empreinte-de-test-{slug}",
            },
        )
        session.execute(
            text(
                "INSERT INTO business_events "
                "(company_id, event_type, aggregate_type, aggregate_id, payload) "
                "VALUES (:company_id, 'stock.updated', 'product', :aggregate_id, '{}'::jsonb)"
            ),
            {"company_id": company_id, "aggregate_id": uuid4()},
        )

    return tenant


def own_row_ids(tenant: Tenant, table: str) -> dict[str, Any]:
    """Critère SQL qui désigne la ligne de `tenant` dans `table`."""
    criteria: dict[str, dict[str, Any]] = {
        "users": {"clause": "id = :value", "value": tenant.user_id},
        "roles": {"clause": "id = :value", "value": tenant.role_id},
        "user_roles": {"clause": "user_id = :value", "value": tenant.user_id},
        "role_permissions": {"clause": "role_id = :value", "value": tenant.role_id},
        # Ces deux tables sont alimentées par les tests qui les concernent ; le
        # critère porte sur le tenant, la RLS étant ce que l'on mesure.
        "auth_sessions": {"clause": "company_id = :value", "value": tenant.company_id},
        "business_events": {"clause": "company_id = :value", "value": tenant.company_id},
    }
    return criteria[table]
