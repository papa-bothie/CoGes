"""Comptes de l'administration pour les tests (ADR 0089)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

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


@contextmanager
def failing_platform_commit(owner_engine: Engine) -> Iterator[None]:
    """Fait échouer au COMMIT toute écriture du journal de la plateforme."""
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE FUNCTION test_platform_fail_at_commit() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'COMMIT refusé (test)'; END $$
                """
            )
        )
        connection.execute(
            text(
                "CREATE CONSTRAINT TRIGGER test_platform_fail_at_commit "
                "AFTER INSERT ON platform_audit_logs DEFERRABLE INITIALLY DEFERRED "
                "FOR EACH ROW EXECUTE FUNCTION test_platform_fail_at_commit()"
            )
        )
    try:
        yield
    finally:
        with owner_engine.begin() as connection:
            connection.execute(
                text("DROP TRIGGER test_platform_fail_at_commit ON platform_audit_logs")
            )
            connection.execute(text("DROP FUNCTION test_platform_fail_at_commit()"))
