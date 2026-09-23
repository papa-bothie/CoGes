"""Module Categories — arbre, unicité, suppression logique, audit.

Les invariants sont vérifiés **par l'API** ici ; ceux qui doivent tenir même sans
elle (FK composites, garde de suppression) sont attaqués directement en base dans
`tests/tenancy/`.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import text

from app.core.errors import sqlstate
from app.core.tenancy import TenantContext, tenant_transaction
from tests.conftest import DemoCompany, auth_headers, read_scalar_in_tenant

pytestmark = pytest.mark.integration


def _create(
    client: TestClient, token: str, name: str, parent_id: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    response = client.post("/api/v1/categories", headers=auth_headers(token), json=payload)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def _unique(prefix: str) -> str:
    """Nom unique : la base de test est partagée par toute la session."""
    return f"{prefix}-{uuid4().hex[:8]}"


def test_a_tree_can_be_built_and_read_back(api_client: TestClient, alpha_token: str) -> None:
    """Racine puis enfant : le parent est bien porté par la fiche lue."""
    root = _create(api_client, alpha_token, _unique("Boissons"))
    child = _create(api_client, alpha_token, _unique("Sodas"), parent_id=root["id"])

    assert root["parent_id"] is None
    assert child["parent_id"] == root["id"]

    response = api_client.get(
        f"/api/v1/categories/{child['id']}", headers=auth_headers(alpha_token)
    )
    assert response.status_code == 200
    assert response.json()["parent_id"] == root["id"]


def test_children_can_be_listed_by_parent(api_client: TestClient, alpha_token: str) -> None:
    """`?parent_id=` ne ramène que les enfants directs, paginés."""
    root = _create(api_client, alpha_token, _unique("Épicerie"))
    _create(api_client, alpha_token, _unique("Riz"), parent_id=root["id"])
    _create(api_client, alpha_token, _unique("Huile"), parent_id=root["id"])

    response = api_client.get(
        f"/api/v1/categories?parent_id={root['id']}", headers=auth_headers(alpha_token)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["parent_id"] for item in body["items"]} == {root["id"]}


def test_search_tolerates_a_typo(api_client: TestClient, alpha_token: str) -> None:
    """La recherche passe par l'index trigramme : « yaour » trouve « Yaourts »."""
    name = _unique("Yaourts")
    created = _create(api_client, alpha_token, name)

    response = api_client.get(
        f"/api/v1/categories?search={name[:9]}", headers=auth_headers(alpha_token)
    )
    assert response.status_code == 200
    assert created["id"] in {item["id"] for item in response.json()["items"]}


def test_a_name_is_unique_under_the_same_parent(api_client: TestClient, alpha_token: str) -> None:
    """Deux sœurs ne portent pas le même nom ; deux cousines le peuvent."""
    name = _unique("Sucré")
    first = _create(api_client, alpha_token, _unique("Rayon-A"))
    second = _create(api_client, alpha_token, _unique("Rayon-B"))
    _create(api_client, alpha_token, name, parent_id=first["id"])

    duplicate = api_client.post(
        "/api/v1/categories",
        headers=auth_headers(alpha_token),
        json={"name": name, "parent_id": first["id"]},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "category_name_taken"

    # Le même nom sous un autre parent reste libre.
    elsewhere = api_client.post(
        "/api/v1/categories",
        headers=auth_headers(alpha_token),
        json={"name": name, "parent_id": second["id"]},
    )
    assert elsewhere.status_code == 201


def test_a_name_is_free_again_after_a_soft_delete(api_client: TestClient, alpha_token: str) -> None:
    """`categories_name_uq` ne porte que sur les lignes vivantes."""
    name = _unique("Surgelés")
    first = _create(api_client, alpha_token, name)

    deleted = api_client.delete(
        f"/api/v1/categories/{first['id']}", headers=auth_headers(alpha_token)
    )
    assert deleted.status_code == 200

    again = api_client.post(
        "/api/v1/categories", headers=auth_headers(alpha_token), json={"name": name}
    )
    assert again.status_code == 201
    assert again.json()["id"] != first["id"]


def test_a_category_cannot_become_its_own_descendant(
    api_client: TestClient, alpha_token: str
) -> None:
    """Déplacer un parent sous son propre enfant fermerait l'arbre sur lui-même."""
    root = _create(api_client, alpha_token, _unique("Maison"))
    child = _create(api_client, alpha_token, _unique("Cuisine"), parent_id=root["id"])
    grandchild = _create(api_client, alpha_token, _unique("Casseroles"), parent_id=child["id"])

    for target in (child["id"], grandchild["id"], root["id"]):
        response = api_client.patch(
            f"/api/v1/categories/{root['id']}",
            headers=auth_headers(alpha_token),
            json={"parent_id": target},
        )
        assert response.status_code == 409, target
        assert response.json()["error"]["code"] == "category_cycle"


def test_a_category_can_be_moved_back_to_the_root(api_client: TestClient, alpha_token: str) -> None:
    """`parent_id: null` transmis explicitement remonte la catégorie à la racine."""
    root = _create(api_client, alpha_token, _unique("Bureau"))
    child = _create(api_client, alpha_token, _unique("Papeterie"), parent_id=root["id"])

    response = api_client.patch(
        f"/api/v1/categories/{child['id']}",
        headers=auth_headers(alpha_token),
        json={"parent_id": None},
    )
    assert response.status_code == 200
    assert response.json()["parent_id"] is None


def test_renaming_does_not_move_the_category(api_client: TestClient, alpha_token: str) -> None:
    """Un corps sans `parent_id` laisse la place de la catégorie inchangée."""
    root = _create(api_client, alpha_token, _unique("Hygiène"))
    child = _create(api_client, alpha_token, _unique("Savons"), parent_id=root["id"])

    response = api_client.patch(
        f"/api/v1/categories/{child['id']}",
        headers=auth_headers(alpha_token),
        json={"name": _unique("Savonnettes")},
    )
    assert response.status_code == 200
    assert response.json()["parent_id"] == root["id"]


def test_a_category_with_children_cannot_be_deleted(
    api_client: TestClient, alpha_token: str
) -> None:
    """La suppression logique d'un parent encore peuplé est refusée."""
    root = _create(api_client, alpha_token, _unique("Textile"))
    child = _create(api_client, alpha_token, _unique("Pagnes"), parent_id=root["id"])

    refused = api_client.delete(
        f"/api/v1/categories/{root['id']}", headers=auth_headers(alpha_token)
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "category_has_children"

    # L'enfant parti, le parent devient supprimable.
    assert (
        api_client.delete(
            f"/api/v1/categories/{child['id']}", headers=auth_headers(alpha_token)
        ).status_code
        == 200
    )
    assert (
        api_client.delete(
            f"/api/v1/categories/{root['id']}", headers=auth_headers(alpha_token)
        ).status_code
        == 200
    )


def test_a_deleted_category_disappears_from_reads_and_is_audited(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Suppression **logique** : la ligne reste, la lecture ne la voit plus, l'audit la garde."""
    category = _create(api_client, alpha_token, _unique("Divers"))

    assert (
        api_client.delete(
            f"/api/v1/categories/{category['id']}", headers=auth_headers(alpha_token)
        ).status_code
        == 200
    )

    gone = api_client.get(f"/api/v1/categories/{category['id']}", headers=auth_headers(alpha_token))
    assert gone.status_code == 404

    # La ligne est toujours là, avec son `deleted_at` : rien n'est effacé.
    still_there = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM categories WHERE id = :id AND deleted_at IS NOT NULL",
        {"id": category["id"]},
    )
    assert still_there == 1

    audited = read_scalar_in_tenant(
        session_factory,
        company_alpha.company_id,
        "SELECT count(*) FROM audit_logs "
        "WHERE entity_table = 'categories' AND entity_id = :id AND action = 'delete'",
        {"id": category["id"]},
    )
    assert audited == 1


def test_a_parent_from_another_company_is_not_found(
    api_client: TestClient, alpha_token: str, beta_token: str
) -> None:
    """Le `parent_id` du corps est soumis à la même règle que celui du chemin : 404."""
    foreign = _create(api_client, beta_token, _unique("Catégorie de Beta"))

    response = api_client.post(
        "/api/v1/categories",
        headers=auth_headers(alpha_token),
        json={"name": _unique("Tentative"), "parent_id": foreign["id"]},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_a_blank_name_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """Le schéma refuse un nom blanc avant que le `CHECK` de la base n'ait à le faire."""
    response = api_client.post(
        "/api/v1/categories", headers=auth_headers(alpha_token), json={"name": "   "}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_the_guard_holds_against_a_direct_database_write(
    api_client: TestClient,
    alpha_token: str,
    company_alpha: DemoCompany,
    session_factory: sessionmaker[Any],
) -> None:
    """Sans passer par l'API : l'UPDATE brut est refusé par `categories_guard_soft_delete`.

    Le service pré-vérifie les sous-catégories pour rendre la main vite, mais c'est
    le trigger qui fait autorité — sinon la règle ne vaudrait que pour les appelants
    polis (§ 10 du Modèle de données).
    """
    root = _create(api_client, alpha_token, _unique("Quincaillerie"))
    _create(api_client, alpha_token, _unique("Clous"), parent_id=root["id"])

    ctx = TenantContext(user_id=company_alpha.manager_id, company_id=company_alpha.company_id)
    with (
        pytest.raises(DBAPIError) as excinfo,
        tenant_transaction(ctx, session_factory=session_factory) as session,
    ):
        session.execute(
            text("UPDATE categories SET deleted_at = now() WHERE id = :id"),
            {"id": root["id"]},
        )

    assert sqlstate(excinfo.value) == "CG001"


def test_an_unknown_field_is_refused(api_client: TestClient, alpha_token: str) -> None:
    """`extra="forbid"` : un champ inconnu n'est jamais ignoré en silence."""
    response = api_client.post(
        "/api/v1/categories",
        headers=auth_headers(alpha_token),
        json={"name": _unique("Étrange"), "couleur": "rouge"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
