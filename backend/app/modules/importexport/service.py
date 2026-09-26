"""Import et export des référentiels et des ventes (module Import/Export, ADR 0041).

**Import** — tout ou rien, dans la transaction de la requête :

* chaque ligne est préparée (schémas des modules), puis écrite par la façade du module
  sous son propre `SAVEPOINT`. Une ligne refusée par la base ou par une règle métier
  est annulée seule et rapportée, et l'import **continue** : le rapport donne toutes
  les erreurs d'un coup, pas la première ;
* le tout est enveloppé dans un `SAVEPOINT` de fichier : en simulation (`dry_run`), ou
  dès qu'une erreur existe, il est annulé. Rien n'est écrit — ni référentiel, ni
  audit, ni événement. Sinon il est confirmé, et le COMMIT de la requête publie tout.

La simulation exécute donc **exactement** le chemin réel : un doublon en base, un
trigger, une contrainte y sont vus comme ils le seraient à l'import.

**Export** — les référentiels sont exportés dans la requête, bornés à
`MAX_SYNC_EXPORT_ROWS` ; les ventes d'une période sont un export volumineux, confié
au worker, qui écrit le fichier dans `export_files`, servi ensuite par l'API.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, CogesError, NotFoundError, ValidationFailedError
from app.core.tenancy import TenantContext
from app.modules.categories import service as categories_service
from app.modules.companies import service as companies_service
from app.modules.customers import service as customers_service
from app.modules.importexport.importers import (
    IMPORTERS,
    WRITE_ERROR_COLUMNS,
    RowRejectedError,
    initial_state,
)
from app.modules.importexport.models import ExportFile
from app.modules.importexport.repository import ExportFileRepository
from app.modules.importexport.schemas import (
    ExportFormat,
    ImportKind,
    ImportReport,
    ImportRowError,
    ReferentialKind,
    SalesExportCreate,
)
from app.modules.importexport.tabular import (
    UnreadableFileError,
    read_table,
    write_csv,
    write_xlsx,
)
from app.modules.products import service as products_service
from app.modules.sales import service as sales_service
from app.modules.suppliers import service as suppliers_service

logger = logging.getLogger(__name__)

#: Lignes par fichier importé. Au-delà, la transaction dépasserait le budget de
#: durée d'une fonction Vercel ; un catalogue plus grand se découpe.
MAX_IMPORT_ROWS = 5000

#: Lignes d'un export de référentiel servi dans la requête.
MAX_SYNC_EXPORT_ROWS = 10_000

#: Plafond de `export_files.content` (révision 0013).
MAX_EXPORT_BYTES = 10 * 1024 * 1024

#: Page de lecture des façades : leur maximum (`?page_size=` borné à 100).
_PAGE = 100


class ImportInvalidError(ValidationFailedError):
    """Au moins une ligne est refusée : rien n'a été écrit."""

    code = "import_invalid"
    default_message = "Le fichier contient des erreurs : aucune ligne n'a été importée."


class ImportFileUnreadableError(ValidationFailedError):
    code = "import_file_unreadable"
    default_message = "Le fichier est illisible : envoyez un CSV ou un fichier Excel (.xlsx)."


class ImportTooLargeError(ValidationFailedError):
    code = "import_too_large"
    default_message = f"Un import compte au plus {MAX_IMPORT_ROWS} lignes : découpez le fichier."


class ExportTooLargeError(BusinessRuleError):
    code = "export_too_large"
    default_message = (
        f"Plus de {MAX_SYNC_EXPORT_ROWS} lignes : cet export est trop volumineux pour être "
        "servi immédiatement."
    )


class ExportNotReadyError(BusinessRuleError):
    code = "export_not_ready"
    default_message = "Le fichier n'est pas disponible : export en cours, en échec ou expiré."


# ------------------------------------------------------------------- import


def import_file(
    session: Session,
    ctx: TenantContext,
    kind: ImportKind,
    content: bytes,
    *,
    dry_run: bool,
    ip_address: str | None = None,
) -> ImportReport:
    """Valide puis importe un fichier ; lève `ImportInvalidError` (422) s'il a des erreurs."""
    importer = IMPORTERS[kind]
    try:
        table = read_table(content, max_rows=MAX_IMPORT_ROWS)
    except UnreadableFileError as exc:
        raise ImportFileUnreadableError(str(exc)) from exc
    if len(table.rows) > MAX_IMPORT_ROWS:
        raise ImportTooLargeError(details={"max_rows": MAX_IMPORT_ROWS})

    errors: list[ImportRowError] = [
        ImportRowError(row=1, column=header, code="missing_column", message="Colonne absente.")
        for header in importer.missing_headers(table.headers)
    ]
    created = 0
    if not errors:
        state = initial_state(session, ctx)
        file_savepoint = session.begin_nested()
        try:
            for row in table.rows:
                try:
                    payload = importer.prepare(row, state)
                except RowRejectedError as rejected:
                    errors.extend(rejected.errors)
                    continue
                try:
                    with session.begin_nested():
                        importer.write(session, ctx, payload, state, ip_address)
                except CogesError as exc:
                    column = WRITE_ERROR_COLUMNS.get(exc.code)
                    errors.append(
                        ImportRowError(
                            row=row.number, column=column, code=exc.code, message=exc.message
                        )
                    )
                    continue
                except DBAPIError:
                    logger.warning("Ligne d'import refusée par la base", exc_info=True)
                    errors.append(
                        ImportRowError(
                            row=row.number,
                            column=None,
                            code="rejected_by_database",
                            message="La base a refusé cette ligne.",
                        )
                    )
                    continue
                created += 1
        except BaseException:
            file_savepoint.rollback()
            raise
        # Simulation, ou fichier fautif : rien ne sort du savepoint de fichier.
        if dry_run or errors:
            file_savepoint.rollback()
        else:
            file_savepoint.commit()

    report = ImportReport(
        kind=kind,
        dry_run=dry_run,
        rows=len(table.rows),
        created=0 if errors and not dry_run else created,
        errors=errors,
    )
    if errors and not dry_run:
        raise ImportInvalidError(details=report.model_dump(mode="json"))
    return report


def import_template(kind: ImportKind) -> bytes:
    """En-têtes attendus pour un type d'import, en CSV vide."""
    return write_csv(IMPORTERS[kind].headers, [])


# ------------------------------------------------------ export des référentiels


def _pages[ItemT](fetch: Callable[[int], tuple[Sequence[ItemT], int]]) -> Iterator[ItemT]:
    """Parcourt une façade paginée jusqu'au bout, en refusant un volume excessif."""
    page = 1
    while True:
        items, total = fetch(page)
        if total > MAX_SYNC_EXPORT_ROWS:
            raise ExportTooLargeError(details={"rows": total, "max_rows": MAX_SYNC_EXPORT_ROWS})
        yield from items
        if page * _PAGE >= total:
            return
        page += 1


def _category_rows(session: Session, ctx: TenantContext) -> list[list[Any]]:
    categories = list(
        _pages(
            lambda page: categories_service.list_categories(
                session, ctx, page=page, page_size=_PAGE
            )
        )
    )
    names = {category.id: category.name for category in categories}
    # Parents d'abord : le fichier se réimporte ligne à ligne sans référence en avant.
    depth: dict[UUID, int] = {}

    def level(category_id: UUID | None) -> int:
        if category_id is None or category_id not in names:
            return 0
        if category_id not in depth:
            parent = next(c.parent_id for c in categories if c.id == category_id)
            depth[category_id] = 1 + level(parent)
        return depth[category_id]

    ordered = sorted(categories, key=lambda category: (level(category.id), category.name))
    return [
        [category.name, names.get(category.parent_id, "") if category.parent_id else ""]
        for category in ordered
    ]


def _product_rows(session: Session, ctx: TenantContext) -> list[list[Any]]:
    pairs = list(
        _pages(
            lambda page: products_service.list_products(session, ctx, page=page, page_size=_PAGE)
        )
    )
    category_names = categories_service.get_names(
        session, ctx, [product.category_id for product, _ in pairs if product.category_id]
    )
    return [
        [
            product.sku,
            product.name,
            price.unit_price if price else None,
            category_names.get(product.category_id, "") if product.category_id else "",
            product.unit,
            product.barcode,
            product.default_tax_rate,
            price.cost_price if price else None,
            product.reorder_point,
            product.is_stock_tracked,
            None,
            None,
        ]
        for product, price in pairs
    ]


def _customer_rows(session: Session, ctx: TenantContext) -> list[list[Any]]:
    customers = _pages(
        lambda page: customers_service.list_customers(session, ctx, page=page, page_size=_PAGE)
    )
    return [
        [customer.name, customer.code, customer.phone, customer.email, customer.credit_limit]
        for customer in customers
    ]


def _supplier_rows(session: Session, ctx: TenantContext) -> list[list[Any]]:
    suppliers = _pages(
        lambda page: suppliers_service.list_suppliers(session, ctx, page=page, page_size=_PAGE)
    )
    return [
        [supplier.name, supplier.code, supplier.phone, supplier.payment_terms_days]
        for supplier in suppliers
    ]


_REFERENTIAL_ROWS: dict[str, Callable[[Session, TenantContext], list[list[Any]]]] = {
    "categories": _category_rows,
    "products": _product_rows,
    "customers": _customer_rows,
    "suppliers": _supplier_rows,
}


@dataclass(frozen=True, slots=True)
class ExportedFile:
    filename: str
    media_type: str
    content: bytes
    row_count: int


MEDIA_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _render(headers: Sequence[str], rows: list[list[Any]], fmt: ExportFormat, name: str) -> bytes:
    if fmt == "csv":
        return write_csv(headers, rows)
    return write_xlsx(headers, rows, title=name)


def export_referential(
    session: Session, ctx: TenantContext, kind: ReferentialKind, fmt: ExportFormat
) -> ExportedFile:
    """Référentiel complet, aux colonnes de l'import : le fichier se réimporte tel quel."""
    rows = _REFERENTIAL_ROWS[kind](session, ctx)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return ExportedFile(
        filename=f"{kind}-{stamp}.{fmt}",
        media_type=MEDIA_TYPES[fmt],
        content=_render(IMPORTERS[kind].headers, rows, fmt, kind),
        row_count=len(rows),
    )


# ------------------------------------------------------------ export des ventes

SALES_HEADERS = (
    "numero",
    "date",
    "statut",
    "client",
    "sous_total",
    "remise",
    "taxes",
    "total",
    "paye",
    "retourne",
)

_SALE_STATUS_LABELS = {"confirmed": "confirmée", "cancelled": "annulée", "draft": "brouillon"}


def request_sales_export(
    session: Session, ctx: TenantContext, payload: SalesExportCreate
) -> ExportFile:
    """Enregistre la demande ; le fichier est produit par le worker (`build_sales_export`)."""
    export = ExportFileRepository(session, ctx).add(
        ExportFile(
            company_id=ctx.company_id,
            kind="sales",
            format=payload.format,
            params={
                "date_from": payload.date_from.isoformat(),
                "date_to": payload.date_to.isoformat(),
            },
            requested_by=ctx.user_id,
        )
    )
    session.flush()
    session.refresh(export)
    return export


def _sales_rows(
    session: Session, ctx: TenantContext, date_from: str, date_to: str
) -> list[list[Any]]:
    zone = ZoneInfo(companies_service.get_timezone(session, ctx))
    start = datetime.combine(datetime.fromisoformat(date_from).date(), time.min, zone)
    end = datetime.combine(datetime.fromisoformat(date_to).date(), time.min, zone) + timedelta(
        days=1
    )
    rows: list[list[Any]] = []
    for status in ("confirmed", "cancelled"):
        page = 1
        while True:
            sales, total, returned = sales_service.list_sales(
                session,
                ctx,
                page=page,
                page_size=_PAGE,
                status=status,
                date_from=start,
                date_to=end - timedelta(microseconds=1),
            )
            customers = customers_service.names_by_ids(
                session, ctx, [sale.customer_id for sale in sales if sale.customer_id]
            )
            for sale in sales:
                rows.append(
                    [
                        sale.sale_no,
                        sale.sold_at.astimezone(zone).strftime("%d/%m/%Y %H:%M"),
                        _SALE_STATUS_LABELS.get(sale.status, sale.status),
                        customers.get(sale.customer_id, "") if sale.customer_id else "",
                        sale.subtotal,
                        sale.discount_total,
                        sale.tax_total,
                        sale.total,
                        sale.paid_total,
                        returned.get(sale.id),
                    ]
                )
            if page * _PAGE >= total:
                break
            page += 1
    rows.sort(key=lambda row: str(row[0]))
    return rows


def build_sales_export(session: Session, ctx: TenantContext, export_id: UUID) -> str:
    """Produit le fichier d'un export en attente (worker). Renvoie le statut final.

    Verrouille la ligne : deux livraisons de la même tâche ne produisent pas deux
    fois le fichier. Un export déjà traité est laissé tel quel.
    """
    repository = ExportFileRepository(session, ctx)
    export = repository.get_for_update(export_id)
    if export is None:
        raise NotFoundError("Export introuvable.")
    if export.status != "pending":
        return export.status

    rows = _sales_rows(session, ctx, export.params["date_from"], export.params["date_to"])
    fmt: ExportFormat = "csv" if export.format == "csv" else "xlsx"
    content = _render(SALES_HEADERS, rows, fmt, "ventes")
    export.completed_at = datetime.now(UTC)
    export.row_count = len(rows)
    if len(content) > MAX_EXPORT_BYTES:
        export.status = "failed"
        export.error = "Fichier trop volumineux : réduisez la période."
        return export.status
    export.content = content
    export.filename = (
        f"ventes-{export.params['date_from']}-au-{export.params['date_to']}.{export.format}"
    )
    export.status = "ready"
    return export.status


def mark_export_failed(session: Session, ctx: TenantContext, export_id: UUID, reason: str) -> None:
    export = ExportFileRepository(session, ctx).get_for_update(export_id)
    if export is not None and export.status == "pending":
        export.status = "failed"
        export.error = reason[:500]
        export.completed_at = datetime.now(UTC)


def get_export(session: Session, ctx: TenantContext, export_id: UUID) -> ExportFile:
    export = ExportFileRepository(session, ctx).get(export_id)
    if export is None:
        raise NotFoundError("Export introuvable.")
    return export


def list_exports(session: Session, ctx: TenantContext, *, limit: int = 20) -> Sequence[ExportFile]:
    return ExportFileRepository(session, ctx).recent(limit=limit)


def export_content(session: Session, ctx: TenantContext, export_id: UUID) -> ExportedFile:
    export = get_export(session, ctx, export_id)
    if export.status != "ready" or export.expires_at <= datetime.now(UTC):
        raise ExportNotReadyError(details={"status": export.status})
    content = ExportFileRepository(session, ctx).content_of(export_id) or b""
    return ExportedFile(
        filename=export.filename or f"export.{export.format}",
        media_type=MEDIA_TYPES[export.format],
        content=content,
        row_count=export.row_count or 0,
    )


def expire_exports(session: Session, ctx: TenantContext) -> int:
    """Vide les fichiers de plus de 24 h ; les lignes restent (aucun DELETE)."""
    return ExportFileRepository(session, ctx).expire_before(datetime.now(UTC))


def pending_export_ids(session: Session, ctx: TenantContext) -> list[UUID]:
    return ExportFileRepository(session, ctx).pending_ids()


def requesters(
    session: Session, ctx: TenantContext, export_ids: Sequence[UUID]
) -> dict[UUID, UUID]:
    """Auteur de chaque export : le worker agit en son nom (audit, contexte)."""
    repository = ExportFileRepository(session, ctx)
    found = {export_id: repository.get(export_id) for export_id in export_ids}
    return {export_id: export.requested_by for export_id, export in found.items() if export}
