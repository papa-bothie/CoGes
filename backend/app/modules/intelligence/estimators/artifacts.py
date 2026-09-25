"""Artefacts de modèle, **hors base** (§ 6), sur le volume du worker (ADR 0035).

Un fichier JSON par entreprise, modèle et version :
`<racine>/<company_id>/<model_name>/<model_version>.json`. JSON et jamais pickle :
un artefact se relit sans exécuter de code, et se lit à l'œil quand on doute d'une
prévision. Le chemin est recopié dans `forecasts.metadata`.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, company_id: UUID, model_name: str, model_version: str) -> Path:
        return self.root / str(company_id) / model_name / f"{model_version}.json"

    def save(
        self, company_id: UUID, model_name: str, model_version: str, payload: dict[str, Any]
    ) -> Path:
        """Écriture atomique : un worker concurrent ne lit jamais un fichier à moitié écrit."""
        target = self.path(company_id, model_name, model_version)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, target)
        return target

    def load(self, company_id: UUID, model_name: str, model_version: str) -> dict[str, Any] | None:
        target = self.path(company_id, model_name, model_version)
        if not target.exists():
            return None
        loaded: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
        return loaded
