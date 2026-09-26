"""Le contrat OpenAPI versionné est à jour (phase 10).

`backend/openapi.json` est la source des types du frontend (`frontend/types/`, générés,
jamais écrits à la main). Une route, un schéma ou un code modifié sans régénérer le
fichier ferait diverger le front en silence : ce test l'interdit.

Pour mettre à jour : `uv run --directory backend python -m app.cli export-openapi`.
"""

from __future__ import annotations

from app.cli import OPENAPI_PATH, openapi_document


def test_versioned_openapi_matches_the_application() -> None:
    assert OPENAPI_PATH.exists(), "backend/openapi.json absent : lancez `app.cli export-openapi`"
    assert OPENAPI_PATH.read_text(encoding="utf-8") == openapi_document(), (
        "Le contrat de l'API a changé : régénérez backend/openapi.json avec "
        "`uv run --directory backend python -m app.cli export-openapi` et versionnez-le."
    )
