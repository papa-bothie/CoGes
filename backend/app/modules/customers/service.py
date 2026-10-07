"""Façade de services du module Customers.

Customers ne dépend que de Companies, c'est-à-dire du contexte tenant : aucun
import d'un autre module métier (Diagramme 3).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.codes import CODE_ATTEMPTS, format_code
from app.core.errors import BusinessRuleError, NotFoundError, sqlstate
from app.core.search import normalise_term
from app.core.tenancy import TenantContext
from app.modules.customers.models import Customer
from app.modules.customers.repository import CustomerRepository
from app.modules.customers.schemas import CustomerCreate, CustomerUpdate

#: Préfixe des codes attribués automatiquement (ADR 0013).
CODE_PREFIX = "CLI"

#: `unique_violation` : deux clients de la même entreprise pour un seul code.
_UNIQUE_VIOLATION = "23505"

# --------------------------------------------------------------- erreurs métier


class CustomerCodeTakenError(BusinessRuleError):
    code = "customer_code_taken"
    default_message = "Un client utilise déjà ce code."


# ------------------------------------------------------------------- lectures


def list_customers(
    session: Session,
    ctx: TenantContext,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    exclude_ids: Sequence[UUID] = (),
) -> tuple[Sequence[Customer], int]:
    """Page de clients vivants. `exclude_ids` sert la liste de vente, qui montre les
    clients récents en tête et ne doit pas les répéter ensuite (ADR 0063)."""
    repository = CustomerRepository(session, ctx)
    term = normalise_term(search)
    return (
        repository.page_live(page=page, page_size=page_size, search=term, exclude_ids=exclude_ids),
        repository.count_live(search=term, exclude_ids=exclude_ids),
    )


def get_many(session: Session, ctx: TenantContext, customer_ids: Sequence[UUID]) -> list[Customer]:
    """Clients vivants de ce lot, **dans l'ordre demandé**. Un client supprimé est absent."""
    found = {c.id: c for c in CustomerRepository(session, ctx).live_by_ids(customer_ids)}
    return [found[customer_id] for customer_id in customer_ids if customer_id in found]


def get_customer(session: Session, ctx: TenantContext, customer_id: UUID) -> Customer:
    """Client du tenant courant. Celui d'une autre entreprise donne 404."""
    customer = CustomerRepository(session, ctx).get_live(customer_id)
    if customer is None:
        raise NotFoundError("Client introuvable.")
    return customer


def names_by_ids(
    session: Session, ctx: TenantContext, customer_ids: Sequence[UUID]
) -> dict[UUID, str]:
    """Noms des clients d'un lot d'identifiants, pour les listes de la bande E.

    Un client supprimé est simplement absent : une liste d'accueil affiche alors
    « client anonyme » plutôt que de disparaître.
    """
    return CustomerRepository(session, ctx).names_by_ids(customer_ids)


def assert_exists(session: Session, ctx: TenantContext, customer_id: UUID) -> None:
    """Façade pour les modules qui référencent un client (Sales, Debts)."""
    get_customer(session, ctx, customer_id)


def get_credit_limit(session: Session, ctx: TenantContext, customer_id: UUID) -> Decimal | None:
    """Encours autorisé du client, ou `None` s'il n'a aucun plafond.

    Façade pour Finance, qui refuse une vente à crédit avant de l'écrire. Les deux
    absences de plafond ne se confondent pas : `None` veut dire « aucune limite »,
    `0` veut dire « crédit interdit ». Le trigger `debt_credit_limit` reste
    l'autorité — ce contrôle-ci sert à nommer le montant qui manque (ADR 0014).
    """
    return get_customer(session, ctx, customer_id).credit_limit


# ------------------------------------------------------------------- écritures


def _assert_code_is_free(
    repository: CustomerRepository, code: str, *, excluding: UUID | None = None
) -> None:
    existing = repository.get_by_code(code)
    if existing is not None and existing.id != excluding:
        raise CustomerCodeTakenError(details={"code": code})


def create_customer(session: Session, ctx: TenantContext, payload: CustomerCreate) -> Customer:
    """Crée un client, avec un code attribué d'office si l'appelant n'en donne pas.

    Le code proposé vient du plus grand compteur du tenant. Deux créations
    simultanées peuvent viser le même numéro : `customers_code_uq` en refuse une,
    et la boucle en calcule un autre. L'unicité vient de la base, jamais du calcul.
    """
    repository = CustomerRepository(session, ctx)
    if payload.code is not None:
        _assert_code_is_free(repository, payload.code)

    for attempt in range(CODE_ATTEMPTS):
        code = payload.code or format_code(CODE_PREFIX, repository.max_code_number(CODE_PREFIX) + 1)
        savepoint = session.begin_nested()
        customer = repository.add(
            Customer(
                company_id=ctx.company_id,
                code=code,
                name=payload.name,
                phone=payload.phone,
                email=None if payload.email is None else str(payload.email),
                credit_limit=payload.credit_limit,
            )
        )
        try:
            session.flush()
        except IntegrityError as exc:
            savepoint.rollback()
            # Un code imposé par l'appelant ne se corrige pas tout seul, et une
            # violation d'une autre contrainte n'a rien à voir avec la numérotation.
            if payload.code is not None or sqlstate(exc) != _UNIQUE_VIOLATION:
                raise
            if attempt == CODE_ATTEMPTS - 1:
                raise CustomerCodeTakenError(details={"code": code}) from exc
            continue
        savepoint.commit()
        return customer

    raise AssertionError("boucle de numérotation sortie sans résultat")  # pragma: no cover


def update_customer(
    session: Session, ctx: TenantContext, customer_id: UUID, payload: CustomerUpdate
) -> Customer:
    """Modifie la fiche client, code compris."""
    repository = CustomerRepository(session, ctx)
    customer = get_customer(session, ctx, customer_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return customer

    if changes.get("code") is not None:
        _assert_code_is_free(repository, changes["code"], excluding=customer.id)
    if "email" in changes and changes["email"] is not None:
        changes["email"] = str(changes["email"])

    for field, value in changes.items():
        setattr(customer, field, value)
    session.flush()
    return customer


def delete_customer(
    session: Session,
    ctx: TenantContext,
    customer_id: UUID,
    *,
    ip_address: str | None = None,
) -> Customer:
    """Suppression **logique**, auditée : un client porte des dettes et un historique."""
    customer = get_customer(session, ctx, customer_id)

    before = {"name": customer.name, "deleted_at": customer.deleted_at}
    customer.deleted_at = datetime.now(UTC)
    session.flush()

    audit_critical(
        session,
        ctx,
        action=AuditAction.DELETE,
        entity_table="customers",
        entity_id=customer.id,
        before=before,
        after={"name": customer.name, "deleted_at": customer.deleted_at},
        ip_address=ip_address,
    )
    return customer
