"""Accès aux données du module Import/Export : `export_files`, filtrée par tenant."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import update

from app.core.repository import TenantRepository
from app.modules.importexport.models import ExportFile


class ExportFileRepository(TenantRepository[ExportFile]):
    model = ExportFile

    def get_for_update(self, export_id: UUID) -> ExportFile | None:
        """Export du tenant, verrouillé : un seul worker le produit."""
        stmt = self._select().where(ExportFile.id == export_id).with_for_update()
        return self.session.execute(stmt).scalar_one_or_none()

    def content_of(self, export_id: UUID) -> bytes | None:
        """Contenu seul, chargé à la demande (colonne différée)."""
        stmt = self._select().where(ExportFile.id == export_id)
        export = self.session.execute(stmt).scalar_one_or_none()
        return None if export is None else export.content

    def recent(self, *, limit: int) -> Sequence[ExportFile]:
        stmt = self._select().order_by(ExportFile.created_at.desc()).limit(limit)
        return self.session.execute(stmt).scalars().all()

    def expire_before(self, moment: datetime) -> int:
        """Vide les fichiers périmés ; la ligne reste comme trace (aucun DELETE)."""
        stmt = (
            update(ExportFile)
            .where(
                ExportFile.company_id == self.ctx.company_id,
                ExportFile.expires_at <= moment,
                ExportFile.status != "expired",
            )
            .values(status="expired", content=None)
        )
        return int(self.session.execute(stmt).rowcount)  # type: ignore[attr-defined]

    def pending_ids(self) -> list[UUID]:
        stmt = self._select().where(ExportFile.status == "pending")
        return [export.id for export in self.session.execute(stmt).scalars()]
