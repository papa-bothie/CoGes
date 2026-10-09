"""Une ligne de fichier → un appel de façade, pour chacun des quatre référentiels.

Chaque importeur fait deux choses, dans cet ordre :

1. `prepare` : transforme les cellules en schémas **de création des modules eux-mêmes**
   (`ProductCreate`, `CustomerCreate`…), avec leurs bornes. Aucune règle n'est
   recopiée ici : une cellule refusée l'est par le même validateur que l'API ;
2. `write` : appelle la façade du module (`create_product`, `record_movement`…).
   Jamais un repository, jamais un modèle d'un autre module (décision 01).

Les colonnes portent des mots simples (« Référence », « Prix de vente »), comparés sans
casse, accents ni petits mots (`Prix de vente` = `prix_vente`). Les anciens en-têtes
techniques (`sku`, `taux_taxe`…) restent reconnus comme alias (ADR 0069). La liste de
chaque importeur est aussi celle de l'export du même référentiel : un fichier exporté se
réimporte tel quel.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext
from app.modules.categories import service as categories_service
from app.modules.categories.schemas import CategoryCreate
from app.modules.customers import service as customers_service
from app.modules.customers.schemas import CustomerCreate
from app.modules.importexport.schemas import ImportKind, ImportRowError
from app.modules.importexport.tabular import Row, Table, normalise_header, plain
from app.modules.inventory import service as inventory_service
from app.modules.inventory.schemas import MovementCreate
from app.modules.products import service as products_service
from app.modules.products.schemas import ProductCreate
from app.modules.suppliers import service as suppliers_service
from app.modules.suppliers.schemas import SupplierCreate


class RowRejectedError(Exception):
    """Une ligne refusée avant écriture ; porte ses erreurs."""

    def __init__(self, errors: list[ImportRowError]) -> None:
        super().__init__(errors)
        self.errors = errors


# ------------------------------------------------------------------ cellules


_SPACES = str.maketrans("", "", "    '")

_TRUE = frozenset({"oui", "o", "vrai", "true", "1", "x", "yes"})
_FALSE = frozenset({"non", "n", "faux", "false", "0", "no"})

#: Écritures usuelles des unités, vers la valeur de l'ENUM `ProductUnit`.
_UNITS = {
    "piece": "piece",
    "pieces": "piece",
    "pce": "piece",
    "pcs": "piece",
    "u": "piece",
    "unite": "piece",
    "kg": "kg",
    "kilo": "kg",
    "kilogramme": "kg",
    "l": "litre",
    "litre": "litre",
    "litres": "litre",
    "carton": "carton",
    "cartons": "carton",
    "m": "metre",
    "metre": "metre",
    "metres": "metre",
    "paquet": "paquet",
    "paquets": "paquet",
    "sac": "sac",
    "sacs": "sac",
    "bouteille": "bouteille",
    "bouteilles": "bouteille",
    "btl": "bouteille",
}


def number_text(value: str) -> str:
    """`1 234,50` → `1234.50` ; `1.234,50` → `1234.50` ; `12.5` inchangé.

    Rend une **chaîne** : la conversion en `Decimal` et ses bornes restent l'affaire
    des validateurs de `app.core.money`, qui refusent les flottants.
    """
    compact = value.translate(_SPACES)
    if "," in compact and "." in compact:
        compact = compact.replace(".", "").replace(",", ".")
    elif "," in compact:
        compact = compact.replace(",", ".")
    return compact


def rate_text(value: str) -> str:
    """`18 %` → `0.18` ; `0,18` → `0.18`."""
    compact = number_text(value)
    if compact.endswith("%"):
        try:
            return str(Decimal(compact[:-1]) / 100)
        except InvalidOperation:
            return compact
    return compact


def _bool(value: str) -> bool | str:
    lowered = value.strip().casefold()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    return value  # laissé tel quel : Pydantic le refusera en nommant la colonne


# ------------------------------------------------------------------ importeurs


@dataclass
class ImportState:
    """Ce qu'un import apprend en avançant : noms de catégories, codes déjà vus."""

    categories: dict[str, list[UUID]] = field(default_factory=dict)
    seen: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Column:
    """Une colonne : son mot (modèle, export, rapport d'erreur) et ses anciens noms."""

    header: str
    field: str | None
    required: bool = False
    convert: Callable[[str], Any] | None = None
    aliases: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        """Clé des cellules d'une ligne : l'en-tête normalisé."""
        return normalise_header(self.header)

    @property
    def keys(self) -> frozenset[str]:
        return frozenset({self.key, *(normalise_header(alias) for alias in self.aliases)})


@dataclass(frozen=True)
class Importer:
    kind: ImportKind
    columns: tuple[Column, ...]
    prepare: Callable[[Row, ImportState], Any]
    write: Callable[[Session, TenantContext, Any, ImportState, str | None], None]

    @property
    def headers(self) -> list[str]:
        return [column.header for column in self.columns]

    def missing_headers(self, present: list[str]) -> list[str]:
        """Colonnes obligatoires absentes d'une table déjà ramenée aux clés (`canonical`)."""
        return [
            column.header
            for column in self.columns
            if column.required and column.key not in present
        ]

    def canonical(self, table: Table) -> Table:
        """Renomme chaque en-tête reconnu (mot ou ancien nom) vers la clé de sa colonne."""
        rename = {key: column.key for column in self.columns for key in column.keys}
        headers = [rename.get(header, header) for header in table.headers]
        rows = [
            Row(
                number=row.number,
                cells={rename.get(header, header): value for header, value in row.cells.items()},
            )
            for row in table.rows
        ]
        return Table(headers=headers, rows=rows)


def _error(row: Row, column: str | None, code: str, message: str) -> ImportRowError:
    return ImportRowError(row=row.number, column=column, code=code, message=message)


def _values(row: Row, columns: tuple[Column, ...]) -> tuple[dict[str, Any], list[ImportRowError]]:
    """Cellules non vides → champs du schéma ; une colonne obligatoire vide est une erreur."""
    data: dict[str, Any] = {}
    errors: list[ImportRowError] = []
    for column in columns:
        raw = row.cells.get(column.key, "").strip()
        if not raw:
            if column.required:
                errors.append(
                    _error(row, column.header, "required", "Cette colonne est obligatoire.")
                )
            continue
        if column.field is not None:
            data[column.field] = column.convert(raw) if column.convert else raw
    return data, errors


def _validate[ModelT: BaseModel](
    model: type[ModelT], data: dict[str, Any], row: Row, columns: tuple[Column, ...]
) -> ModelT:
    """Valide avec le schéma du module ; chaque erreur est rattachée à sa colonne."""
    by_field = {column.field: column.header for column in columns if column.field}
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        errors = []
        for detail in exc.errors():
            location = detail["loc"][0] if detail["loc"] else None
            column = by_field.get(str(location)) if location is not None else None
            message = str(detail["msg"]).removeprefix("Value error, ")
            errors.append(_error(row, column, "invalid_value", message))
        raise RowRejectedError(errors) from exc


def _check_unique(state: ImportState, row: Row, column: str, value: str | None) -> None:
    """Même code deux fois dans le fichier : la seconde ligne est refusée.

    `column` est le mot de la colonne, repris tel quel dans le rapport.
    """
    if not value:
        return
    key = f"{column}:{value.casefold()}"
    first = state.seen.get(key)
    if first is not None:
        raise RowRejectedError(
            [
                _error(
                    row,
                    column,
                    "duplicate_in_file",
                    f"Valeur déjà présente à la ligne {first} du fichier.",
                )
            ]
        )
    state.seen[key] = row.number


def _category_id(state: ImportState, row: Row, column: str, name: str) -> UUID:
    matches = state.categories.get(name.casefold(), [])
    if not matches:
        raise RowRejectedError(
            [_error(row, column, "category_not_found", f"Catégorie « {name} » introuvable.")]
        )
    if len(matches) > 1:
        raise RowRejectedError(
            [
                _error(
                    row,
                    column,
                    "category_ambiguous",
                    f"Plusieurs catégories s'appellent « {name} » : renommez-en une.",
                )
            ]
        )
    return matches[0]


# ----------------------------------------------------------------- catégories

_NAME = Column("Nom", "name", required=True)
_PARENT = Column("Parent", None)
_CATEGORY_COLUMNS = (_NAME, _PARENT)


def _prepare_category(row: Row, state: ImportState) -> CategoryCreate:
    data, errors = _values(row, _CATEGORY_COLUMNS)
    if errors:
        raise RowRejectedError(errors)
    parent = row.cells.get(_PARENT.key, "").strip()
    if parent:
        data["parent_id"] = _category_id(state, row, _PARENT.header, parent)
    _check_unique(state, row, _NAME.header, f"{parent}/{data.get('name', '')}")
    return _validate(CategoryCreate, data, row, _CATEGORY_COLUMNS)


def _write_category(
    session: Session,
    ctx: TenantContext,
    payload: CategoryCreate,
    state: ImportState,
    ip: str | None,
) -> None:
    category = categories_service.create_category(session, ctx, payload)
    # Visible des lignes suivantes : un produit du même lot peut s'y rattacher.
    state.categories.setdefault(payload.name.casefold(), []).append(category.id)


# ------------------------------------------------------------------- produits


@dataclass(frozen=True, slots=True)
class PreparedProduct:
    product: ProductCreate
    initial: MovementCreate | None


# La référence est facultative : vide, elle est générée (`ART-0001`, ADR 0066).
_SKU = Column("Référence", "sku", aliases=("sku",))
_CATEGORY = Column("Catégorie", None)
_BARCODE = Column("Code-barres", "barcode")
_INITIAL_QTY = Column("Stock initial", "qty_delta")
_INITIAL_COST = Column("Coût unitaire", "unit_cost")
_PRODUCT_COLUMNS = (
    _SKU,
    _NAME,
    Column("Prix de vente", "unit_price", required=True, convert=number_text),
    _CATEGORY,
    Column("Unité", "unit", convert=lambda value: _UNITS.get(plain(value), value)),
    _BARCODE,
    Column("TVA", "default_tax_rate", convert=rate_text, aliases=("taux_taxe",)),
    Column("Prix d'achat", "cost_price", convert=number_text),
    Column("Seuil d'alerte", "reorder_point", convert=number_text, aliases=("seuil_reappro",)),
    Column("Suivi du stock", "is_stock_tracked", convert=_bool),
    Column(_INITIAL_QTY.header, None),
    Column(_INITIAL_COST.header, None),
)


def _prepare_product(row: Row, state: ImportState) -> PreparedProduct:
    data, errors = _values(row, _PRODUCT_COLUMNS)
    if errors:
        raise RowRejectedError(errors)
    _check_unique(state, row, _SKU.header, data.get("sku"))
    _check_unique(state, row, _BARCODE.header, data.get("barcode"))
    category = row.cells.get(_CATEGORY.key, "").strip()
    if category:
        data["category_id"] = _category_id(state, row, _CATEGORY.header, category)
    product = _validate(ProductCreate, data, row, _PRODUCT_COLUMNS)

    quantity = number_text(row.cells.get(_INITIAL_QTY.key, "").strip())
    if not quantity or quantity in {"0", "0.0", "0.000"}:
        return PreparedProduct(product=product, initial=None)
    if not product.is_stock_tracked:
        raise RowRejectedError(
            [
                _error(
                    row,
                    _INITIAL_QTY.header,
                    "initial_stock_untracked",
                    "Un produit sans suivi de stock ne reçoit pas de stock initial.",
                )
            ]
        )
    cost = number_text(row.cells.get(_INITIAL_COST.key, "").strip())
    if not cost and product.cost_price is not None:
        cost = str(product.cost_price)
    if not cost:
        raise RowRejectedError(
            [
                _error(
                    row,
                    _INITIAL_COST.header,
                    "initial_cost_required",
                    "Un stock initial exige un coût unitaire (ou un prix d'achat).",
                )
            ]
        )
    movement_columns = (_INITIAL_QTY, _INITIAL_COST)
    # Identifiant provisoire : le produit n'existe pas encore. Il est remplacé à
    # l'écriture ; seule la cohérence quantité / coût est vérifiée ici.
    initial = _validate(
        MovementCreate,
        {"product_id": uuid4(), "type": "initial", "qty_delta": quantity, "unit_cost": cost},
        row,
        movement_columns,
    )
    return PreparedProduct(product=product, initial=initial)


def _write_product(
    session: Session,
    ctx: TenantContext,
    payload: PreparedProduct,
    state: ImportState,
    ip: str | None,
) -> None:
    product, _price = products_service.create_product(session, ctx, payload.product, ip_address=ip)
    if payload.initial is not None:
        # Le stock initial passe par un mouvement `initial` : Inventory reste le seul
        # à écrire le stock, et le CMP part du coût saisi (§ 5.6).
        inventory_service.record_movement(
            session,
            ctx,
            payload.initial.model_copy(update={"product_id": product.id}),
            ip_address=ip,
        )


# ------------------------------------------------------- clients, fournisseurs

_CODE = Column("Code", "code")
_PHONE = Column("Téléphone", "phone")
_CUSTOMER_COLUMNS = (
    _NAME,
    _CODE,
    _PHONE,
    Column("E-mail", "email", aliases=("email",)),
    Column("Plafond de crédit", "credit_limit", convert=number_text),
)


def _prepare_customer(row: Row, state: ImportState) -> CustomerCreate:
    data, errors = _values(row, _CUSTOMER_COLUMNS)
    if errors:
        raise RowRejectedError(errors)
    _check_unique(state, row, _CODE.header, data.get("code"))
    return _validate(CustomerCreate, data, row, _CUSTOMER_COLUMNS)


def _write_customer(
    session: Session,
    ctx: TenantContext,
    payload: CustomerCreate,
    state: ImportState,
    ip: str | None,
) -> None:
    customers_service.create_customer(session, ctx, payload)


_SUPPLIER_COLUMNS = (
    _NAME,
    _CODE,
    _PHONE,
    Column("Délai de paiement (jours)", "payment_terms_days", convert=number_text),
)


def _prepare_supplier(row: Row, state: ImportState) -> SupplierCreate:
    data, errors = _values(row, _SUPPLIER_COLUMNS)
    if errors:
        raise RowRejectedError(errors)
    _check_unique(state, row, _CODE.header, data.get("code"))
    return _validate(SupplierCreate, data, row, _SUPPLIER_COLUMNS)


def _write_supplier(
    session: Session,
    ctx: TenantContext,
    payload: SupplierCreate,
    state: ImportState,
    ip: str | None,
) -> None:
    suppliers_service.create_supplier(session, ctx, payload)


IMPORTERS: dict[str, Importer] = {
    "categories": Importer("categories", _CATEGORY_COLUMNS, _prepare_category, _write_category),
    "products": Importer("products", _PRODUCT_COLUMNS, _prepare_product, _write_product),
    "customers": Importer("customers", _CUSTOMER_COLUMNS, _prepare_customer, _write_customer),
    "suppliers": Importer("suppliers", _SUPPLIER_COLUMNS, _prepare_supplier, _write_supplier),
}

#: Colonne probable d'une erreur métier renvoyée par une façade.
WRITE_ERROR_COLUMNS = {
    "product_sku_taken": _SKU.header,
    "product_barcode_taken": _BARCODE.header,
    "customer_code_taken": _CODE.header,
    "supplier_code_taken": _CODE.header,
    "category_name_taken": _NAME.header,
    "not_found": None,
}


def initial_state(session: Session, ctx: TenantContext) -> ImportState:
    return ImportState(categories=categories_service.ids_by_name(session, ctx))
