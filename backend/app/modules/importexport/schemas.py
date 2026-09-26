"""Schémas du module Import/Export."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

type ImportKind = Literal["categories", "products", "customers", "suppliers"]
type ReferentialKind = Literal["categories", "products", "customers", "suppliers"]
type ExportFormat = Literal["csv", "xlsx"]
type ExportStatus = Literal["pending", "ready", "failed", "expired"]

#: Une période d'export de ventes ne dépasse pas un an : au-delà, le fichier
#: approcherait le plafond de 10 Mo de `export_files`.
MAX_EXPORT_DAYS = 366


class ImportRowError(BaseModel):
    """Une erreur, rattachée à sa ligne (l'en-tête est la ligne 1) et à sa colonne."""

    model_config = ConfigDict(extra="forbid")

    row: int
    column: str | None
    code: str
    message: str


class ImportReport(BaseModel):
    """Rapport d'un import, simulé (`dry_run`) ou réel.

    `created` compte les lignes écrites — ou qui l'auraient été, en simulation. Un
    import réel n'écrit rien dès qu'une seule erreur existe (tout ou rien).
    """

    model_config = ConfigDict(extra="forbid")

    kind: ImportKind
    dry_run: bool
    rows: int
    created: int
    errors: list[ImportRowError]

    @property
    def valid(self) -> bool:
        return not self.errors


class ImportFingerprint(BaseModel):
    """Empreinte d'un import pour la clé d'idempotence : le type et le condensat du fichier."""

    model_config = ConfigDict(extra="forbid")

    kind: ImportKind
    sha256: str


class SalesExportCreate(BaseModel):
    """Période d'un export de ventes, dans le fuseau de l'entreprise, bornes incluses."""

    model_config = ConfigDict(extra="forbid")

    date_from: date
    date_to: date
    format: ExportFormat = "xlsx"

    @model_validator(mode="after")
    def _check_period(self) -> SalesExportCreate:
        if self.date_to < self.date_from:
            raise ValueError("date_to : la fin de période précède son début.")
        if (self.date_to - self.date_from).days >= MAX_EXPORT_DAYS:
            raise ValueError(
                f"date_to : une période d'export ne dépasse pas {MAX_EXPORT_DAYS} jours."
            )
        return self


class ExportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    kind: str
    format: ExportFormat
    status: ExportStatus
    filename: str | None
    row_count: int | None = Field(default=None, ge=0)
    error: str | None
    created_at: datetime
    completed_at: datetime | None
    expires_at: datetime


class ExportList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ExportRead]
