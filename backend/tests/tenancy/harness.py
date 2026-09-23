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

from app.core.tenancy import TenantContext, tenant_transaction

# Tables tenant-scoped couvertes par les tests croisés.
# Chaque phase ajoute les siennes ; T37 vérifie en plus, génériquement, qu'aucune
# table portant `company_id` n'échappe à la RLS.
TENANT_TABLES: tuple[str, ...] = ("users", "roles", "user_roles", "role_permissions")

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


def create_permission(owner_engine: Engine, code: str) -> UUID:
    """Ajoute une entrée au catalogue global `permissions`.

    Écrite avec le rôle **propriétaire** : `coges_app` n'a que SELECT sur ce
    catalogue (ADR 0004), et le vocabulaire des droits est livré par migration,
    jamais par un tenant.
    """
    permission_id = uuid4()
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO permissions (id, code, resource, action) "
                "VALUES (:id, :code, :resource, 'read')"
            ),
            {"id": permission_id, "code": code, "resource": code.split(".")[0]},
        )
    return permission_id


def create_tenant(session_factory: sessionmaker[Any], owner_engine: Engine, slug: str) -> Tenant:
    """Crée une entreprise complète : société, utilisateur, rôle, rattachement."""
    company_id = uuid4()
    user_id = uuid4()
    role_id = uuid4()
    email = f"gerant@{slug}.test"

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
                "password_hash": PLACEHOLDER_PASSWORD_HASH,
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

    permission_id = create_permission(owner_engine, f"{slug}.read")
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

    return tenant


def own_row_ids(tenant: Tenant, table: str) -> dict[str, Any]:
    """Critère SQL qui désigne la ligne de `tenant` dans `table`."""
    criteria: dict[str, dict[str, Any]] = {
        "users": {"clause": "id = :value", "value": tenant.user_id},
        "roles": {"clause": "id = :value", "value": tenant.role_id},
        "user_roles": {"clause": "user_id = :value", "value": tenant.user_id},
        "role_permissions": {"clause": "role_id = :value", "value": tenant.role_id},
    }
    return criteria[table]
