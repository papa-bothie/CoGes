"""Revue des schémas Pydantic (décision 16, ADR 0042).

Tout modèle reçu dans un corps de requête refuse les champs inconnus
(`extra="forbid"`) : un client qui envoie `company_id`, `unit_cost` ou `status` là où
le serveur ne les attend pas reçoit un 422, pas un silence. Le test lit le contrat
OpenAPI — `extra="forbid"` s'y traduit par `additionalProperties: false` — : un nouvel
endpoint y est soumis sans intervention.
"""

from __future__ import annotations

from typing import Any

from app.main import app

REF_PREFIX = "#/components/schemas/"


def _refs(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(REF_PREFIX):
            found.add(ref.removeprefix(REF_PREFIX))
        for value in node.values():
            found |= _refs(value)
    elif isinstance(node, list):
        for value in node:
            found |= _refs(value)
    return found


def _request_schemas(spec: dict[str, Any]) -> set[str]:
    schemas: dict[str, Any] = spec["components"]["schemas"]
    pending: set[str] = set()
    for operations in spec["paths"].values():
        for operation in operations.values():
            body = operation.get("requestBody", {}).get("content", {})
            for media, content in body.items():
                # Un téléversement multipart est un fichier, pas un objet métier.
                if media == "application/json":
                    pending |= _refs(content)
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        pending |= _refs(schemas[name]) - seen
    return seen


def test_contract_has_request_bodies() -> None:
    assert len(_request_schemas(app.openapi())) >= 20


def test_every_request_body_model_forbids_extra_fields() -> None:
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    lax = sorted(
        name
        for name in _request_schemas(spec)
        if schemas[name].get("type") == "object"
        and schemas[name].get("additionalProperties") is not False
    )
    assert not lax, "Schémas de requête sans extra='forbid' :\n" + "\n".join(lax)
