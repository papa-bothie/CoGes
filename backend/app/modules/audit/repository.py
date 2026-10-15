"""Requêtes du module Audit — `audit_logs` de l'entreprise du contexte, en lecture.

`audit_logs` est partitionnée et n'a pas de modèle ORM (sa clé est `(id,
occurred_at)`, pas un UUID) : la lecture est écrite en SQL Core. Le filtre
`company_id` est posé ici **et** par la RLS de chaque partition (ADR 0008).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from app.core.tenancy import TenantContext

_COLUMNS = """
    id, actor_user_id, action, entity_table, entity_id, diff,
    host(ip_address) AS ip_address, occurred_at
"""

_FILTERS = """
    company_id = :company_id
    AND (CAST(:actor_user_id AS uuid) IS NULL OR actor_user_id = CAST(:actor_user_id AS uuid))
    AND (CAST(:action AS text) IS NULL OR action = CAST(:action AS text))
    AND (CAST(:entity_table AS text) IS NULL OR entity_table = CAST(:entity_table AS text))
    AND (CAST(:entity_id AS uuid) IS NULL OR entity_id = CAST(:entity_id AS uuid))
    AND (CAST(:period_from AS timestamptz) IS NULL
         OR occurred_at >= CAST(:period_from AS timestamptz))
    AND (CAST(:period_to AS timestamptz) IS NULL
         OR occurred_at <= CAST(:period_to AS timestamptz))
    AND (NOT CAST(:notable_only AS boolean) OR NOT (
         entity_table IN ('auth_sessions', 'payment_allocations', 'product_stock')
         OR action IN ('login', 'rebuild')
         OR (entity_table = 'sales' AND action = 'confirm')
         OR (entity_table IN ('payments', 'debts') AND action = 'insert'
             AND diff -> 'after' ->> 'sale_id' IS NOT NULL)
         OR (entity_table = 'payments' AND action = 'insert'
             AND diff -> 'after' ->> 'expense_id' IS NOT NULL)
         OR (entity_table = 'debts' AND action = 'cancel'
             AND diff -> 'after' ->> 'by_sale_cancel' = 'true')))
"""

_PAGE = text(
    f"SELECT {_COLUMNS} FROM audit_logs WHERE {_FILTERS} "
    "ORDER BY occurred_at DESC, id DESC LIMIT :limit OFFSET :offset"
)
_COUNT = text(f"SELECT count(*) FROM audit_logs WHERE {_FILTERS}")


class AuditLogRepository:
    """Journal d'une entreprise. Ni UPDATE ni DELETE : la table les refuse."""

    def __init__(self, session: Session, ctx: TenantContext) -> None:
        self.session = session
        self.ctx = ctx

    def _params(
        self,
        *,
        actor_user_id: UUID | None,
        action: str | None,
        entity_table: str | None,
        entity_id: UUID | None,
        period_from: datetime | None,
        period_to: datetime | None,
        notable_only: bool = False,
    ) -> dict[str, Any]:
        return {
            "company_id": self.ctx.company_id,
            "actor_user_id": actor_user_id,
            "action": action,
            "entity_table": entity_table,
            "entity_id": entity_id,
            "period_from": period_from,
            "period_to": period_to,
            "notable_only": notable_only,
        }

    def page(self, *, page: int, page_size: int, **filters: Any) -> Sequence[Row[Any]]:
        params = self._params(**filters) | {"limit": page_size, "offset": (page - 1) * page_size}
        return self.session.execute(_PAGE, params).all()

    def count(self, **filters: Any) -> int:
        return int(self.session.execute(_COUNT, self._params(**filters)).scalar_one())
