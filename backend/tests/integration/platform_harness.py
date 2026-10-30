"""Comptes de l'administration pour les tests (ADR 0089)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core import mfa, totp
from app.core.deps import platform_transaction
from app.modules.platform import service as platform_service

DEVICE_COOKIE = "coges_platform_device"
PLATFORM_PASSWORD = "mot-de-passe-plateforme-01"  # noqa: S105 - valeur factice de test


@dataclass(frozen=True, slots=True)
class PlatformAccount:
    id: UUID
    email: str
    role: str
    #: Secret TOTP en clair, connu du test seulement (ADR 0105) ; `None` : à enrôler.
    mfa_secret: str | None = None


def create_platform_account(role: str, *, enrolled: bool = True) -> PlatformAccount:
    """Passe par la vraie fonction de la CLI, sous `coges_app_platform`. Par défaut, la
    double authentification est déjà active (`--mfa-secret`, accepté en CI)."""
    email = f"{role}-{uuid4().hex[:8]}@equipe.example.com"
    secret = totp.generate_secret() if enrolled else None
    account_id = platform_service.create_platform_user(
        email=email,
        display_name=f"Équipe {role}",
        role=role,
        password=PLATFORM_PASSWORD,
        mfa_secret=secret,
    )
    return PlatformAccount(id=account_id, email=email, role=role, mfa_secret=secret)


def forget_last_code(account: PlatformAccount) -> None:
    """Oublie le dernier pas accepté : un test peut se reconnecter dans la même
    fenêtre de 30 s. L'anti-rejeu a ses propres tests, qui n'appellent pas ceci."""
    with platform_transaction() as session:
        session.execute(
            text("UPDATE platform_users SET mfa_last_step = NULL WHERE id = :id"),
            {"id": account.id},
        )


def _known_device(client: TestClient, account: PlatformAccount) -> None:
    existing = [cookie for cookie in client.cookies.jar if cookie.name == DEVICE_COOKIE]
    raw = existing[0].value if existing and existing[0].value else f"appareil-{uuid4().hex}"
    for cookie in existing:
        client.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)
    agent = str(client.headers.get("user-agent", ""))
    with platform_transaction() as session:
        session.execute(
            text(
                "INSERT INTO platform_known_devices (platform_user_id, token_hash, browser) "
                "VALUES (:id, :hash, :browser) ON CONFLICT DO NOTHING"
            ),
            {
                "id": account.id,
                "hash": mfa.opaque_token_digest(raw),
                "browser": mfa.browser_label(agent),
            },
        )
    client.cookies.set(DEVICE_COOKIE, raw, path="/api/v1/platform/auth")


def password_step(
    client: TestClient, account: PlatformAccount, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/platform/auth/login",
        json={"email": account.email, "password": PLATFORM_PASSWORD},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def current_code(account: PlatformAccount) -> str:
    assert account.mfa_secret is not None, "compte sans double authentification"
    return totp.code_at(account.mfa_secret, totp.current_step())


def platform_login_response(
    client: TestClient, account: PlatformAccount, headers: dict[str, str] | None = None
) -> Response:
    """Mot de passe puis code calculé ici : la session complète, comme l'écran.

    L'appareil du client de test est déclaré connu d'avance : les tests qui comptent
    les tâches enfilées ne voient pas l'alerte « nouvel appareil », qui a ses propres
    tests (`test_platform_mfa.py`)."""
    forget_last_code(account)
    _known_device(client, account)
    step = password_step(client, account, headers)
    assert step["step"] == "verify", step
    response = client.post(
        "/api/v1/platform/auth/mfa/verify",
        json={"challenge_token": step["challenge_token"], "code": current_code(account)},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response


def platform_login(client: TestClient, account: PlatformAccount) -> str:
    return str(platform_login_response(client, account).json()["access_token"])


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
