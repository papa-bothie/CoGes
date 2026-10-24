"""Historique des réglages (écran 24d, ADR 0075) : le journal d'audit en phrases.

L'audit ne garde que des identifiants et des montants ; les noms (vente n°, article,
client, personne) appartiennent aux modules qui les possèdent. Audit est en bande
Plateforme et ne peut pas les appeler : la phrase se fabrique ici, en bande E, par les
façades. Une ligne qu'on ne sait pas raconter garde une phrase générique, jamais une
ligne vide.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.display import fcfa, qty
from app.core.errors import NotFoundError
from app.core.tenancy import TenantContext
from app.modules.audit.schemas import AuditLogRead
from app.modules.expenses import service as expenses_service
from app.modules.finance import service as finance_service
from app.modules.inventory import service as inventory_service
from app.modules.products import service as products_service
from app.modules.rbac import service as rbac_service
from app.modules.users import service as users_service

#: Raisons d'une correction de stock (ADR 0067), comme à l'écran 10.
REASONS: dict[str, str] = {
    "damaged": "abîmé",
    "expired": "périmé",
    "lost_or_stolen": "perdu ou volé",
    "home_use": "pris pour la maison",
    "count_error": "erreur de comptage",
    "found": "retrouvé",
    "supplier_gift": "cadeau du fournisseur",
}

#: Unités au singulier et au pluriel (révision 0015).
UNITS: dict[str, tuple[str, str]] = {
    "piece": ("pièce", "pièces"),
    "kg": ("kg", "kg"),
    "litre": ("litre", "litres"),
    "carton": ("carton", "cartons"),
    "metre": ("mètre", "mètres"),
    "paquet": ("paquet", "paquets"),
    "sac": ("sac", "sacs"),
    "bouteille": ("bouteille", "bouteilles"),
}

#: Ce dont parle une ligne qu'on ne sait pas raconter mieux.
THINGS: dict[str, str] = {
    "sales": "une vente",
    "sale_returns": "un retour",
    "products": "un article",
    "product_prices": "un prix",
    "inventory_movements": "le stock",
    "customers": "un client",
    "suppliers": "un fournisseur",
    "categories": "un rayon",
    "expenses": "une dépense",
    "expense_categories": "un type de dépense",
    "payments": "un paiement",
    "debts": "une dette",
    "users": "une personne",
    "user_roles": "les droits d'une personne",
    "roles": "un rôle",
    "companies": "les réglages de la boutique",
    "support_sessions": "un accès support",
}

GENERIC_VERBS: dict[str, str] = {
    "insert": "a ajouté",
    "update": "a modifié",
    "delete": "a supprimé",
    "cancel": "a annulé",
    "confirm": "a confirmé",
    "export": "a exporté",
}


def first_name(full_name: str | None) -> str:
    """« Fatou Diop » → « Fatou » ; une action sans auteur vient de CoGes."""
    if not full_name or not full_name.strip():
        return "CoGes"
    return full_name.split()[0]


def initials(full_name: str | None) -> str:
    """« Fatou Diop » → « FD », « Modou » → « MO »."""
    if not full_name or not full_name.strip():
        return "CG"
    words = full_name.split()
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


def of(name: str) -> str:
    """« de Moussa », « d’Awa » : élision devant une voyelle."""
    return f"d’{name}" if name[:1].lower() in "aeiouyéèêàâîôûh" else f"de {name}"


def short_no(document_no: str | None) -> str:
    """« V-001042 » → « 1042 », comme les alertes (ADR 0074)."""
    if not document_no:
        return "?"
    return document_no.split("-")[-1].lstrip("0") or document_no


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except InvalidOperation:
        return None


def _money(value: Any) -> str:
    amount = _decimal(value)
    return fcfa(amount) if amount is not None else "?"


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def _side(log: AuditLogRead, side: str) -> dict[str, Any]:
    payload = (log.diff or {}).get(side)
    return payload if isinstance(payload, dict) else {}


@dataclass
class _Names:
    """Les noms d'une page, lus par lots aux façades avant d'écrire les phrases."""

    products: dict[UUID, Any] = field(default_factory=dict)
    users: dict[UUID, str] = field(default_factory=dict)
    payment_parties: dict[UUID, str] = field(default_factory=dict)
    debt_parties: dict[UUID, str] = field(default_factory=dict)
    deliveries: set[UUID] = field(default_factory=set)
    roles: dict[UUID, str] = field(default_factory=dict)
    categories: dict[UUID, str] = field(default_factory=dict)


def _gather(session: Session, ctx: TenantContext, logs: Sequence[AuditLogRead]) -> _Names:
    names = _Names()
    product_ids: set[UUID] = set()
    user_ids: set[UUID] = set()
    payment_ids: set[UUID] = set()
    debt_ids: set[UUID] = set()
    role_ids: set[UUID] = set()
    category_ids: set[UUID] = set()
    for log in logs:
        after, before = _side(log, "after"), _side(log, "before")
        if log.entity_table in ("product_prices", "inventory_movements"):
            product_id = _uuid(after.get("product_id") or before.get("product_id"))
            if product_id:
                product_ids.add(product_id)
        elif log.entity_table == "products" and log.entity_id:
            product_ids.add(log.entity_id)
        elif log.entity_table in ("users", "user_roles") and log.entity_id:
            user_ids.add(log.entity_id)
        elif log.entity_table == "payments" and log.entity_id and log.action == "insert":
            payment_ids.add(log.entity_id)
        elif log.entity_table == "debts" and log.entity_id:
            debt_ids.add(log.entity_id)
        elif log.entity_table == "roles" and log.entity_id:
            role_ids.add(log.entity_id)
        elif log.entity_table == "expenses":
            category_id = _uuid(after.get("category_id") or before.get("category_id"))
            if category_id:
                category_ids.add(category_id)

    names.products = dict(products_service.get_summaries(session, ctx, list(product_ids)))
    names.users = users_service.names_by_id(session, ctx, list(user_ids))

    allocations = finance_service.allocations_of_payments(session, ctx, list(payment_ids))
    debt_of_payment = {
        payment_id: items[0].debt_id for payment_id, items in allocations.items() if items
    }
    debts = []
    for debt_id in debt_ids | set(debt_of_payment.values()):
        try:
            debts.append(finance_service.get_debt(session, ctx, debt_id))
        except NotFoundError:
            continue
    names.debt_parties = finance_service.party_names_of_debts(session, ctx, debts)
    names.payment_parties = {
        payment_id: names.debt_parties[debt_id]
        for payment_id, debt_id in debt_of_payment.items()
        if debt_id in names.debt_parties
    }
    names.deliveries = set(inventory_service.delivery_lines(session, ctx, list(debt_ids)))

    for role_id in role_ids:
        try:
            role = rbac_service.get_role(session, ctx, role_id)
        except NotFoundError:
            continue
        names.roles[role_id] = rbac_service.role_label(role)
    for category_id in category_ids:
        try:
            names.categories[category_id] = expenses_service.get_category(
                session, ctx, category_id
            ).name
        except NotFoundError:
            continue
    return names


def _product(names: _Names, log: AuditLogRead) -> str:
    after, before = _side(log, "after"), _side(log, "before")
    product_id = _uuid(after.get("product_id") or before.get("product_id")) or log.entity_id
    summary = names.products.get(product_id) if product_id else None
    return str(summary.name) if summary is not None else "un article"


def _person(names: _Names, log: AuditLogRead) -> str:
    return names.users.get(log.entity_id, "une personne") if log.entity_id else "une personne"


def _stock(names: _Names, log: AuditLogRead, who: str) -> str:
    after = _side(log, "after")
    delta = _decimal(after.get("qty_delta"))
    product_id = _uuid(after.get("product_id"))
    summary = names.products.get(product_id) if product_id else None
    name = str(summary.name) if summary is not None else "un article"
    if log.action == "cancel":
        return f"{who} a annulé une correction du stock {of(name)}"
    if delta is None:
        return f"{who} a corrigé le stock {of(name)}"
    singular, plural = UNITS.get(summary.unit if summary is not None else "", ("", ""))
    unit = singular if abs(delta) <= 1 else plural
    sign = "+" if delta > 0 else "−"
    amount = f"{sign}{qty(abs(delta))}{' ' + unit if unit else ''}"
    reason = REASONS.get(str(after.get("reason_code") or ""))
    return f"{who} a corrigé le stock {of(name)} : {amount}" + (f" ({reason})" if reason else "")


def _sale(log: AuditLogRead, who: str) -> str | None:
    if log.action != "cancel":
        return None
    after = _side(log, "after")
    reason = str(after.get("cancel_reason") or "").strip()
    sentence = f"{who} a annulé la vente n° {short_no(after.get('sale_no'))}"
    return sentence + (f" ({reason[:1].lower()}{reason[1:]})" if reason else "")


def _price(names: _Names, log: AuditLogRead, who: str) -> str:
    name = _product(names, log)
    after, before = _side(log, "after"), _side(log, "before")
    if log.action == "insert":
        return f"{who} a ajouté l’article {name} à {_money(after.get('unit_price'))}"
    if before.get("unit_price") is None:
        return f"{who} a fixé le prix {of(name)} : {_money(after.get('unit_price'))}"
    return (
        f"{who} a changé le prix {of(name)} : "
        f"{_money(before.get('unit_price'))} → {_money(after.get('unit_price'))}"
    )


def _user(names: _Names, log: AuditLogRead, who: str) -> str:
    target = _person(names, log)
    after = _side(log, "after")
    if log.action == "delete":
        return f"{who} a supprimé le compte {of(target)}"
    if "is_active" in after:
        if after["is_active"]:
            return f"{who} a redonné l’accès à {target}"
        return f"{who} a coupé l’accès {of(target)}"
    if after.get("refused") == "temporary_password_expired":
        return f"{who} n’a pas pu se connecter : mot de passe provisoire expiré"
    if after.get("password_changed"):
        if log.actor_user_id == log.entity_id:
            return f"{who} a changé son mot de passe"
        return f"{who} a donné un nouveau mot de passe à {target}"
    return f"{who} a modifié le compte {of(target)}"


def _payment(names: _Names, log: AuditLogRead, who: str) -> str:
    after, before = _side(log, "after"), _side(log, "before")
    if log.action == "cancel":
        cancelled = before.get("payments") or after.get("payments") or []
        amount = (
            cancelled[0].get("amount") if cancelled and isinstance(cancelled[0], dict) else None
        )
        return f"{who} a annulé un paiement de {_money(amount)}"
    amount = _money(after.get("amount"))
    party = names.payment_parties.get(log.entity_id) if log.entity_id else None
    if after.get("direction") == "outflow":
        return f"{who} a payé {amount}" + (f" à {party}" if party else "")
    return f"{who} a encaissé {amount}" + (f" {of(party)}" if party else "")


def _debt(names: _Names, log: AuditLogRead, who: str) -> str:
    after = _side(log, "after")
    party = names.debt_parties.get(log.entity_id) if log.entity_id else None
    if log.action == "cancel":
        return f"{who} a abandonné la dette" + (f" {of(party)}" if party else "")
    if log.entity_id in names.deliveries:
        return f"{who} a reçu une livraison" + (f" {of(party)}" if party else "")
    amount = _money(after.get("principal"))
    if after.get("customer_id"):
        return f"{who} a noté une dette {of(party or 'un client')} : {amount}"
    return f"{who} a noté une dette envers {party or 'un fournisseur'} : {amount}"


def _expense(names: _Names, log: AuditLogRead, who: str) -> str:
    after, before = _side(log, "after"), _side(log, "before")
    state = after or before
    label = str(state.get("label") or "").strip()
    if not label:
        category_id = _uuid(state.get("category_id"))
        label = names.categories.get(category_id, "") if category_id else ""
    what = f" ({label})" if label else ""
    if log.action == "delete":
        return f"{who} a supprimé une dépense de {_money(state.get('amount'))}{what}"
    if log.action == "update":
        return f"{who} a modifié une dépense{what}"
    return f"{who} a noté une dépense de {_money(state.get('amount'))}{what}"


def _role(names: _Names, log: AuditLogRead, who: str) -> str:
    label = names.roles.get(log.entity_id) if log.entity_id else None
    label = label or str(_side(log, "after").get("name") or _side(log, "before").get("name") or "")
    if log.action == "update":
        return f"{who} a changé ce que peut faire le rôle {label}".rstrip()
    verb = GENERIC_VERBS.get(log.action, "a modifié")
    return f"{who} {verb} le rôle {label}".rstrip()


def _return(log: AuditLogRead, who: str) -> str:
    after = _side(log, "after")
    number = short_no(after.get("return_no"))
    if log.action == "update":
        return f"{who} a remboursé le retour n° {number}"
    return f"{who} a enregistré le retour n° {number}"


def _support(log: AuditLogRead) -> str:
    """Accès support (ADR 0092) : l'équipe CoGes, jamais une personne ; le motif cité."""
    if log.action == "update":
        return "L’équipe CoGes a fermé son accès support"
    reason = str(_side(log, "after").get("justification") or "").strip()
    opened = "L’équipe CoGes a ouvert un accès support, en lecture seule"
    return f"{opened}. Motif : « {reason} »" if reason else opened


def sentence(names: _Names, log: AuditLogRead) -> str:
    """La phrase d'une ligne du journal, au passé composé, sujet en tête."""
    who = first_name(log.actor_name)
    table = log.entity_table
    special: dict[str, Callable[[], str | None]] = {
        "sales": lambda: _sale(log, who),
        "product_prices": lambda: _price(names, log, who),
        "inventory_movements": lambda: _stock(names, log, who),
        "users": lambda: _user(names, log, who),
        "user_roles": lambda: (
            # Le premier rôle est donné à la création du compte (qui n'a pas d'autre trace).
            f"{who} a ajouté {_person(names, log)}"
            if not _side(log, "before").get("role_ids")
            else f"{who} a changé le rôle {of(_person(names, log))}"
        ),
        "payments": lambda: _payment(names, log, who),
        "debts": lambda: _debt(names, log, who),
        "expenses": lambda: _expense(names, log, who),
        "roles": lambda: _role(names, log, who),
        "sale_returns": lambda: _return(log, who),
        "products": lambda: (
            f"{who} a retiré l’article {_product(names, log)}" if log.action == "delete" else None
        ),
        "companies": lambda: f"{who} a modifié les réglages de la boutique",
        "support_sessions": lambda: _support(log),
    }
    if log.action == "export":
        return f"{who} a préparé un fichier Excel"
    built = special[table]() if table in special else None
    if built:
        return built
    verb = GENERIC_VERBS.get(log.action, "a modifié")
    return f"{who} {verb} {THINGS.get(table, 'une donnée')}"


def sentences(session: Session, ctx: TenantContext, logs: Sequence[AuditLogRead]) -> list[str]:
    """Les phrases d'une page, noms lus par lots (une requête par façade, pas par ligne)."""
    names = _gather(session, ctx, logs)
    return [sentence(names, log) for log in logs]


__all__ = ["first_name", "initials", "sentences", "short_no"]
