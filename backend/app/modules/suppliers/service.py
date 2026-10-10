"""Façade de services du module Suppliers.

Suppliers ne dépend que de Companies, c'est-à-dire du contexte tenant : aucun
import d'un autre module métier (Diagramme 3).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.codes import CODE_ATTEMPTS, format_code
from app.core.errors import BusinessRuleError, NotFoundError, sqlstate
from app.core.search import normalise_term
from app.core.tenancy import TenantContext
from app.modules.suppliers.models import Supplier
from app.modules.suppliers.repository import SupplierRepository
from app.modules.suppliers.schemas import SupplierCreate, SupplierUpdate

#: Préfixe des codes attribués automatiquement (ADR 0013).
CODE_PREFIX = "FRN"

#: `unique_violation` : deux fournisseurs de la même entreprise pour un seul code.
_UNIQUE_VIOLATION = "23505"

# --------------------------------------------------------------- erreurs métier


class SupplierCodeTakenError(BusinessRuleError):
    code = "supplier_code_taken"
    default_message = "Un fournisseur utilise déjà ce code."


# ------------------------------------------------------------------- lectures


def list_suppliers(
    session: Session,
    ctx: TenantContext,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
) -> tuple[Sequence[Supplier], int]:
    repository = SupplierRepository(session, ctx)
    term = normalise_term(search)
    return (
        repository.page_live(page=page, page_size=page_size, search=term),
        repository.count_live(search=term),
    )


def get_supplier(session: Session, ctx: TenantContext, supplier_id: UUID) -> Supplier:
    """Fournisseur du tenant courant. Celui d'une autre entreprise donne 404."""
    supplier = SupplierRepository(session, ctx).get_live(supplier_id)
    if supplier is None:
        raise NotFoundError("Fournisseur introuvable.")
    return supplier


def names_by_ids(
    session: Session, ctx: TenantContext, supplier_ids: Sequence[UUID]
) -> dict[UUID, str]:
    """Noms des fournisseurs d'un lot d'identifiants (listes de dettes, ADR 0053)."""
    return SupplierRepository(session, ctx).names_by_ids(supplier_ids)


def assert_exists(session: Session, ctx: TenantContext, supplier_id: UUID) -> None:
    """Façade pour les modules qui référencent un fournisseur (Inventory, Debts)."""
    get_supplier(session, ctx, supplier_id)


# ------------------------------------------------------------------- écritures


def _assert_code_is_free(
    repository: SupplierRepository, code: str, *, excluding: UUID | None = None
) -> None:
    existing = repository.get_by_code(code)
    if existing is not None and existing.id != excluding:
        raise SupplierCodeTakenError(details={"code": code})


def create_supplier(session: Session, ctx: TenantContext, payload: SupplierCreate) -> Supplier:
    """Crée un fournisseur, avec un code attribué d'office si aucun n'est fourni.

    Même mécanique que pour les clients : le numéro est calculé à partir des codes
    du tenant, et `suppliers_code_uq` tranche en cas de création simultanée.
    """
    repository = SupplierRepository(session, ctx)
    if payload.code is not None:
        _assert_code_is_free(repository, payload.code)

    for attempt in range(CODE_ATTEMPTS):
        code = payload.code or format_code(CODE_PREFIX, repository.max_code_number(CODE_PREFIX) + 1)
        savepoint = session.begin_nested()
        supplier = repository.add(
            Supplier(
                company_id=ctx.company_id,
                code=code,
                name=payload.name,
                phone=payload.phone,
                payment_terms_days=payload.payment_terms_days,
            )
        )
        try:
            session.flush()
        except IntegrityError as exc:
            savepoint.rollback()
            if payload.code is not None or sqlstate(exc) != _UNIQUE_VIOLATION:
                raise
            if attempt == CODE_ATTEMPTS - 1:
                raise SupplierCodeTakenError(details={"code": code}) from exc
            continue
        savepoint.commit()
        return supplier

    raise AssertionError("boucle de numérotation sortie sans résultat")  # pragma: no cover


def update_supplier(
    session: Session, ctx: TenantContext, supplier_id: UUID, payload: SupplierUpdate
) -> Supplier:
    """Modifie la fiche fournisseur, code compris."""
    repository = SupplierRepository(session, ctx)
    supplier = get_supplier(session, ctx, supplier_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return supplier

    if changes.get("code") is not None:
        _assert_code_is_free(repository, changes["code"], excluding=supplier.id)

    for field, value in changes.items():
        setattr(supplier, field, value)
    session.flush()
    return supplier


def delete_supplier(
    session: Session,
    ctx: TenantContext,
    supplier_id: UUID,
    *,
    ip_address: str | None = None,
) -> Supplier:
    """Suppression **logique**, auditée : un fournisseur porte des dettes et des entrées."""
    supplier = get_supplier(session, ctx, supplier_id)

    before = {"name": supplier.name, "deleted_at": supplier.deleted_at}
    supplier.deleted_at = datetime.now(UTC)
    session.flush()

    audit_critical(
        session,
        ctx,
        action=AuditAction.DELETE,
        entity_table="suppliers",
        entity_id=supplier.id,
        before=before,
        after={"name": supplier.name, "deleted_at": supplier.deleted_at},
        ip_address=ip_address,
    )
    return supplier


#: Plafond de la liste des écrans 13 à 16 : une boutique compte quelques centaines de
#: fournisseurs, la liste entière se lit donc en une requête (ADR 0072).
DIRECTORY_LIMIT = 5000


def directory(
    session: Session, ctx: TenantContext, *, search: str | None = None
) -> tuple[Sequence[Supplier], int]:
    """Tous les fournisseurs vivants qui répondent à la recherche ; leur nombre sans recherche.

    Restitution les classe elle-même (ceux qui doivent d'abord) : elle a besoin de toute
    la liste, pas d'une page déjà triée par nom.
    """
    repository = SupplierRepository(session, ctx)
    term = normalise_term(search)
    return (
        repository.page_live(page=1, page_size=DIRECTORY_LIMIT, search=term),
        repository.count_live(),
    )
