"""Schémas du module Categories.

`extra="forbid"` partout : un champ inconnu est refusé au lieu d'être ignoré
silencieusement (Pydantic strict, § Sécurité de CLAUDE.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

#: Longueur maximale d'un nom de catégorie. La base n'impose que « non vide » ;
#: la borne haute est une règle de saisie, elle appartient au schéma.
NAME_MAX_LENGTH = 120

#: Le nom est **rogné avant** d'être mesuré : une saisie de blancs est refusée par
#: le schéma (422), et non par le `CHECK (length(btrim(name)) > 0)` de la base, qui
#: sortirait en 500. Les espaces de bord ne franchissent jamais l'API.
type CategoryName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH)
]


#: Couleur d'un rayon : l'une des huit de la maquette v2 (écran 12), dans l'ordre de sa palette.
type CategoryColor = Annotated[int, Field(ge=1, le=8)]


class CategoryRead(BaseModel):
    """Vue publique d'une catégorie."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    parent_id: UUID | None
    name: str
    color: int | None
    created_at: datetime


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CategoryName
    parent_id: UUID | None = None
    color: CategoryColor | None = None


class CategoryUpdate(BaseModel):
    """Modification partielle.

    `parent_id: null` **explicitement transmis** remonte la catégorie à la racine ;
    champ absent = inchangé. C'est `exclude_unset` qui distingue les deux cas.
    """

    model_config = ConfigDict(extra="forbid")

    name: CategoryName | None = None
    parent_id: UUID | None = None
    #: `null` explicite efface la couleur : le front la tire alors du nom.
    color: CategoryColor | None = None


class CategoryPage(BaseModel):
    """Page de résultats. La pagination est obligatoire sur toutes les listes."""

    model_config = ConfigDict(extra="forbid")

    items: list[CategoryRead]
    page: int
    page_size: int
    total: int
