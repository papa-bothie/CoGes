"""Comptes de l'administration pour les tests (ADR 0089)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.modules.platform import service as platform_service

PLATFORM_PASSWORD = "mot-de-passe-plateforme-01"  # noqa: S105 - valeur factice de test


@dataclass(frozen=True, slots=True)
class PlatformAccount:
    id: UUID
    email: str
    role: str


def create_platform_account(role: str) -> PlatformAccount:
    """Passe par la vraie fonction de la CLI, sous `coges_app_platform`."""
    email = f"{role}-{uuid4().hex[:8]}@equipe.example.com"
    account_id = platform_service.create_platform_user(
        email=email, display_name=f"Équipe {role}", role=role, password=PLATFORM_PASSWORD
    )
    return PlatformAccount(id=account_id, email=email, role=role)


def platform_login(client: TestClient, account: PlatformAccount) -> str:
    response = client.post(
        "/api/v1/platform/auth/login",
        json={"email": account.email, "password": PLATFORM_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])
