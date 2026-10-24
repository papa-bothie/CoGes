"""L'équipe CoGes gérée depuis l'administration (lot admin 6 ; ADR 0094).

Invitations par e-mail (jeton tiré par le worker, jamais stocké ni transporté en clair),
acceptation à usage unique, changement de profil et suspension sous garde-fous : on ne se
modifie pas soi-même, il reste toujours un administrateur actif, le support n'écrit rien.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.sql import text

from app.core import mailer, queue
from app.main import app
from app.modules.platform import service as platform_service
from app.workers.tasks import platform as platform_tasks
from tests.conftest import TEST_BASE_URL, auth_headers
from tests.integration.platform_harness import (
    PLATFORM_PASSWORD,
    PlatformAccount,
    create_platform_account,
    failing_platform_commit,
    platform_login,
)

TEAM = "/api/v1/platform/team"
INVITATIONS = "/api/v1/platform/team/invitations"
ACCEPT = "/api/v1/platform/auth/accept-invitation"
NEW_PASSWORD = PLATFORM_PASSWORD
INVALID = "invitation_invalid"


@pytest.fixture
def client(platform_bound_to_test_database: None) -> Iterator[TestClient]:
    with TestClient(app, base_url=TEST_BASE_URL) as test_client:
        yield test_client


@pytest.fixture
def administrator(platform_bound_to_test_database: None) -> PlatformAccount:
    return create_platform_account("administrator")


@pytest.fixture
def admin_headers(client: TestClient, administrator: PlatformAccount) -> dict[str, str]:
    return auth_headers(platform_login(client, administrator))


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def _record(task_name: str, **kwargs: Any) -> bool:
        calls.append((task_name, kwargs))
        return True

    monkeypatch.setattr(queue, "enqueue", _record)
    return calls


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """SMTP « configuré » : rien ne part, chaque message est capturé."""
    sent: list[dict[str, Any]] = []

    def _send(*, to: list[str], subject: str, body: str) -> bool:
        sent.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_email", _send)
    return sent


@pytest.fixture
def no_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mailer, "is_configured", lambda: False)


def _email() -> str:
    return f"collegue-{uuid4().hex[:8]}@equipe.example.com"


def _invite(
    client: TestClient,
    headers: dict[str, str],
    *,
    email: str | None = None,
    role: str = "support",
    key: str | None = None,
) -> Any:
    return client.post(
        INVITATIONS,
        headers={**headers, "Idempotency-Key": key or uuid4().hex},
        json={"email": email or _email(), "display_name": "Moussa Badji", "role": role},
    )


def _run_send_task(enqueued: list[tuple[str, dict[str, Any]]]) -> None:
    """Exécute, comme le worker, les envois d'invitation enfilés."""
    for name, kwargs in enqueued:
        if name == platform_service.SEND_INVITATION_TASK:
            platform_tasks.send_invitation.run(
                invitation_id=kwargs["invitation_id"], issue=kwargs["issue"]
            )


def _token_from(message: dict[str, Any]) -> str:
    marker = "/invitation/"
    start = message["body"].index(marker) + len(marker)
    return str(message["body"][start:].split()[0])


def _invitation_row(owner_engine: Engine, invitation_id: str) -> Any:
    with owner_engine.connect() as connection:
        return connection.execute(
            text("SELECT * FROM platform_invitations WHERE id = :id"), {"id": invitation_id}
        ).one()


def _accept(client: TestClient, token: str, password: str = NEW_PASSWORD) -> Any:
    return client.post(ACCEPT, json={"token": token, "password": password})


# ------------------------------------------------------------------- invitations


def test_an_invitation_mails_a_link_whose_token_lives_nowhere_in_clear(
    client: TestClient,
    admin_headers: dict[str, str],
    enqueued: list[tuple[str, dict[str, Any]]],
    smtp: list[dict[str, Any]],
    owner_engine: Engine,
) -> None:
    email = _email()
    response = _invite(client, admin_headers, email=email.upper())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email_sent"] is True
    assert body["invitation_url"] is None
    invitation = body["invitation"]
    assert invitation["email"] == email
    expires = datetime.fromisoformat(invitation["expires_at"]) - datetime.now(UTC)
    assert timedelta(hours=71) < expires <= timedelta(hours=72)

    # La tâche ne transporte que l'identifiant et le numéro d'émission.
    [(name, kwargs)] = enqueued
    assert name == platform_service.SEND_INVITATION_TASK
    assert set(kwargs) == {"countdown", "invitation_id", "issue"}
    assert _invitation_row(owner_engine, invitation["id"]).token_hash is None

    _run_send_task(enqueued)
    [message] = smtp
    assert message["to"] == [email]
    assert "http://localhost:3200/invitation/" in message["body"]
    token = _token_from(message)
    row = _invitation_row(owner_engine, invitation["id"])
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    # Le jeton n'apparaît ni dans la ligne, ni dans le journal.
    with owner_engine.connect() as connection:
        journal = connection.execute(
            text("SELECT diff::text FROM platform_audit_logs WHERE entity_id = :id"),
            {"id": invitation["id"]},
        ).scalars()
        assert all(token not in (diff or "") for diff in journal)
    assert token not in str(dict(row._mapping))


def test_without_smtp_the_link_is_shown_once(
    client: TestClient,
    admin_headers: dict[str, str],
    enqueued: list[tuple[str, dict[str, Any]]],
    no_smtp: None,
    owner_engine: Engine,
) -> None:
    key = uuid4().hex
    email = _email()
    response = _invite(client, admin_headers, email=email, key=key)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email_sent"] is False
    assert body["invitation_url"].startswith("http://localhost:3200/invitation/")
    assert enqueued == []
    token = body["invitation_url"].rsplit("/", 1)[1]
    row = _invitation_row(owner_engine, body["invitation"]["id"])
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()

    # Un double clic (même clé) rend la même invitation, sans montrer le lien une 2ᵉ fois.
    replay = _invite(client, admin_headers, email=email, key=key)
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["invitation"]["id"] == body["invitation"]["id"]
    assert replay.json()["invitation_url"] is None
    # La même clé pour une autre demande : refusée.
    assert _invite(client, admin_headers, key=key).status_code == 422


def test_a_double_click_sends_one_email(
    client: TestClient,
    admin_headers: dict[str, str],
    enqueued: list[tuple[str, dict[str, Any]]],
    smtp: list[dict[str, Any]],
) -> None:
    key = uuid4().hex
    email = _email()
    assert _invite(client, admin_headers, email=email, key=key).status_code == 201
    assert _invite(client, admin_headers, email=email, key=key).status_code == 200
    assert len(enqueued) == 1


def test_accepting_creates_the_account_once_and_signs_in(
    client: TestClient,
    admin_headers: dict[str, str],
    enqueued: list[tuple[str, dict[str, Any]]],
    smtp: list[dict[str, Any]],
) -> None:
    email = _email()
    _invite(client, admin_headers, email=email, role="support")
    _run_send_task(enqueued)
    token = _token_from(smtp[0])

    accepted = _accept(client, token)
    assert accepted.status_code == 200, accepted.text
    assert set(accepted.json()) == {"access_token", "token_type", "expires_in"}
    assert "coges_platform_refresh" in accepted.headers["set-cookie"]
    me = client.get(
        "/api/v1/platform/auth/me", headers=auth_headers(accepted.json()["access_token"])
    )
    assert me.json()["email"] == email
    assert me.json()["role"] == "support"
    assert me.json()["display_name"] == "Moussa Badji"

    # Usage unique : la même réponse que pour un jeton inconnu.
    again = _accept(client, token)
    unknown = _accept(client, "x" * 43)
    assert again.status_code == unknown.status_code == 400
    assert again.json() == unknown.json()
    assert again.json()["error"]["code"] == INVALID

    team = client.get(TEAM, headers=admin_headers).json()
    assert email in {member["email"] for member in team["members"]}
    assert email not in {invitation["email"] for invitation in team["invitations"]}


def test_expired_revoked_and_resent_tokens_are_refused_alike(
    client: TestClient,
    admin_headers: dict[str, str],
    enqueued: list[tuple[str, dict[str, Any]]],
    smtp: list[dict[str, Any]],
    owner_engine: Engine,
) -> None:
    refusals = []

    # Échue.
    expired = _invite(client, admin_headers).json()["invitation"]
    _run_send_task(enqueued)
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE platform_invitations SET created_at = now() - interval '4 days', "
                "expires_at = now() - interval '1 hour' WHERE id = :id"
            ),
            {"id": expired["id"]},
        )
    refusals.append(_accept(client, _token_from(smtp[-1])))

    # Révoquée.
    enqueued.clear()
    revoked = _invite(client, admin_headers).json()["invitation"]
    _run_send_task(enqueued)
    deleted = client.delete(f"{INVITATIONS}/{revoked['id']}", headers=admin_headers)
    assert deleted.status_code == 204
    refusals.append(_accept(client, _token_from(smtp[-1])))

    # Renvoyée : l'ancien lien meurt, le nouveau fonctionne.
    enqueued.clear()
    resent = _invite(client, admin_headers).json()["invitation"]
    _run_send_task(enqueued)
    old_token = _token_from(smtp[-1])
    enqueued.clear()
    again = client.post(f"{INVITATIONS}/{resent['id']}/resend", headers=admin_headers)
    assert again.status_code == 200, again.text
    assert again.json()["email_sent"] is True
    _run_send_task(enqueued)
    new_token = _token_from(smtp[-1])
    assert new_token != old_token
    refusals.append(_accept(client, old_token))

    bodies = [refusal.json() for refusal in refusals]
    assert [refusal.status_code for refusal in refusals] == [400, 400, 400]
    assert bodies[0] == bodies[1] == bodies[2]
    assert _accept(client, new_token).status_code == 200


def test_a_late_send_cannot_resurrect_an_older_issue(
    client: TestClient,
    admin_headers: dict[str, str],
    enqueued: list[tuple[str, dict[str, Any]]],
    smtp: list[dict[str, Any]],
) -> None:
    """Le 1ᵉʳ envoi encore en file après un renvoi n'écrit plus rien, n'envoie rien."""
    invitation = _invite(client, admin_headers).json()["invitation"]
    first = list(enqueued)
    enqueued.clear()
    client.post(f"{INVITATIONS}/{invitation['id']}/resend", headers=admin_headers)
    _run_send_task(enqueued)
    current = _token_from(smtp[-1])
    _run_send_task(first)
    assert len(smtp) == 1
    assert _accept(client, current).status_code == 200


def test_an_email_already_on_the_team_or_invited_is_409(
    client: TestClient,
    admin_headers: dict[str, str],
    administrator: PlatformAccount,
    enqueued: list[tuple[str, dict[str, Any]]],
    smtp: list[dict[str, Any]],
) -> None:
    member = _invite(client, admin_headers, email=administrator.email)
    assert member.status_code == 409
    assert member.json()["error"]["code"] == "platform_user_exists"
    email = _email()
    assert _invite(client, admin_headers, email=email).status_code == 201
    pending = _invite(client, admin_headers, email=email)
    assert pending.status_code == 409
    assert pending.json()["error"]["code"] == "invitation_pending"


def test_an_expired_invitation_makes_room_for_a_new_one(
    client: TestClient,
    admin_headers: dict[str, str],
    enqueued: list[tuple[str, dict[str, Any]]],
    smtp: list[dict[str, Any]],
    owner_engine: Engine,
) -> None:
    email = _email()
    first = _invite(client, admin_headers, email=email).json()["invitation"]
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE platform_invitations SET created_at = now() - interval '4 days', "
                "expires_at = now() - interval '1 hour' WHERE id = :id"
            ),
            {"id": first["id"]},
        )
    assert _invite(client, admin_headers, email=email).status_code == 201
    assert _invitation_row(owner_engine, first["id"]).revoked_at is not None


def test_a_refused_commit_sends_nothing(
    client: TestClient,
    admin_headers: dict[str, str],
    enqueued: list[tuple[str, dict[str, Any]]],
    smtp: list[dict[str, Any]],
    owner_engine: Engine,
) -> None:
    email = _email()
    with failing_platform_commit(owner_engine):
        response = _invite(client, admin_headers, email=email)
    assert response.status_code == 500
    assert enqueued == []
    with owner_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM platform_invitations WHERE email = :email"),
                {"email": email},
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "pas-une-adresse", "display_name": "X", "role": "support"},
        {"email": "a@b.example.com", "display_name": " ", "role": "support"},
        {"email": "a@b.example.com", "display_name": "X", "role": "owner"},
        {"email": "a@b.example.com", "display_name": "X", "role": "support", "extra": 1},
    ],
)
def test_an_impossible_invitation_is_422(
    client: TestClient, admin_headers: dict[str, str], payload: dict[str, Any]
) -> None:
    response = client.post(
        INVITATIONS, headers={**admin_headers, "Idempotency-Key": uuid4().hex}, json=payload
    )
    assert response.status_code == 422


def test_an_invitation_needs_an_idempotency_key(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.post(
        INVITATIONS,
        headers=admin_headers,
        json={"email": _email(), "display_name": "X", "role": "support"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "idempotency_key_required"


def test_a_short_password_is_refused_before_the_token(
    client: TestClient,
    admin_headers: dict[str, str],
    enqueued: list[tuple[str, dict[str, Any]]],
    smtp: list[dict[str, Any]],
) -> None:
    _invite(client, admin_headers)
    _run_send_task(enqueued)
    token = _token_from(smtp[0])
    assert _accept(client, token, password="court").status_code == 422
    # Le jeton n'a pas été consommé.
    assert _accept(client, token).status_code == 200


# ------------------------------------------------------- profils et suspension


def _patch(client: TestClient, headers: dict[str, str], user_id: UUID, **body: Any) -> Any:
    return client.patch(f"{TEAM}/{user_id}", headers=headers, json=body)


def test_a_role_change_counts_at_the_next_request(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    colleague = create_platform_account("support")
    colleague_headers = auth_headers(platform_login(client, colleague))
    # Support : aucune écriture.
    assert _invite(client, colleague_headers).status_code == 403

    promoted = _patch(client, admin_headers, colleague.id, role="administrator")
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "administrator"
    # Même jeton, profil relu en base : l'écriture passe aussitôt.
    assert _invite(client, colleague_headers).status_code == 201

    demoted = _patch(client, admin_headers, colleague.id, role="support")
    assert demoted.status_code == 200
    assert _invite(client, colleague_headers).status_code == 403


def test_a_suspension_needs_a_reason_and_cuts_every_session(
    client: TestClient, admin_headers: dict[str, str], owner_engine: Engine
) -> None:
    colleague = create_platform_account("support")
    colleague_headers = auth_headers(platform_login(client, colleague))
    assert client.get(TEAM, headers=colleague_headers).status_code == 200

    missing = _patch(client, admin_headers, colleague.id, is_active=False)
    assert missing.status_code == 422

    suspended = _patch(
        client, admin_headers, colleague.id, is_active=False, reason="Départ de l'équipe"
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["is_active"] is False
    assert client.get(TEAM, headers=colleague_headers).status_code == 401
    with owner_engine.connect() as connection:
        open_sessions = connection.execute(
            text(
                "SELECT count(*) FROM platform_auth_sessions "
                "WHERE platform_user_id = :id AND revoked_at IS NULL"
            ),
            {"id": colleague.id},
        ).scalar_one()
    assert open_sessions == 0
    refused = client.post(
        "/api/v1/platform/auth/login",
        json={"email": colleague.email, "password": PLATFORM_PASSWORD},
    )
    assert refused.status_code == 401

    # Réactiver : sans raison, le compte se reconnecte.
    reactivated = _patch(client, admin_headers, colleague.id, is_active=True)
    assert reactivated.status_code == 200
    assert platform_login(client, colleague)


def test_every_change_is_audited_before_and_after(
    client: TestClient,
    admin_headers: dict[str, str],
    administrator: PlatformAccount,
    owner_engine: Engine,
) -> None:
    colleague = create_platform_account("support")
    _patch(client, admin_headers, colleague.id, role="administrator")
    _patch(client, admin_headers, colleague.id, is_active=False, reason="Congé long")
    with owner_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT actor_id, action, diff FROM platform_audit_logs "
                "WHERE entity_table = 'platform_users' AND entity_id = :id AND action = 'update' "
                "ORDER BY id"
            ),
            {"id": colleague.id},
        ).all()
    assert [row.diff for row in rows] == [
        {"before": {"role": "support"}, "after": {"role": "administrator"}},
        {"before": {"is_active": True}, "after": {"is_active": False}, "reason": "Congé long"},
    ]
    assert {row.actor_id for row in rows} == {administrator.id}


def test_nobody_changes_their_own_account(
    client: TestClient, admin_headers: dict[str, str], administrator: PlatformAccount
) -> None:
    for body in ({"role": "support"}, {"is_active": False, "reason": "Je pars"}):
        response = _patch(client, admin_headers, administrator.id, **body)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "cannot_modify_self"


def _only_active_administrators(owner_engine: Engine, keep: set[UUID]) -> list[UUID]:
    """Laisse actifs les seuls administrateurs `keep` ; rend ceux à réactiver ensuite."""
    with owner_engine.begin() as connection:
        return list(
            connection.execute(
                text(
                    "UPDATE platform_users SET is_active = false "
                    "WHERE role = 'administrator' AND is_active AND NOT (id = ANY(:keep)) "
                    "RETURNING id"
                ),
                {"keep": list(keep)},
            ).scalars()
        )


def _reactivate(owner_engine: Engine, ids: list[UUID]) -> None:
    with owner_engine.begin() as connection:
        connection.execute(
            text("UPDATE platform_users SET is_active = true WHERE id = ANY(:ids)"),
            {"ids": ids},
        )


def test_removing_one_of_two_administrators_is_allowed(
    client: TestClient, owner_engine: Engine
) -> None:
    first = create_platform_account("administrator")
    second = create_platform_account("administrator")
    first_headers = auth_headers(platform_login(client, first))
    others = _only_active_administrators(owner_engine, {first.id, second.id})
    try:
        assert _patch(client, first_headers, second.id, role="support").status_code == 200
        # Un support suspendu ne retire aucun administrateur : rien à garder.
        assert (
            _patch(client, first_headers, second.id, is_active=False, reason="Départ").status_code
            == 200
        )
    finally:
        _reactivate(owner_engine, others)


def test_two_administrators_cannot_remove_each_other_at_once(
    client: TestClient, owner_engine: Engine
) -> None:
    """Les deux derniers administrateurs se retirent l'un l'autre en même temps : un seul
    geste passe, l'autre reçoit `last_administrator`."""
    first = create_platform_account("administrator")
    second = create_platform_account("administrator")
    headers = {
        first.id: auth_headers(platform_login(client, first)),
        second.id: auth_headers(platform_login(client, second)),
    }
    others = _only_active_administrators(owner_engine, {first.id, second.id})
    results: dict[UUID, int] = {}
    barrier = threading.Barrier(2)

    def _remove(actor: UUID, target: UUID) -> None:
        with TestClient(app, base_url=TEST_BASE_URL) as own:
            barrier.wait()
            response = own.patch(
                f"{TEAM}/{target}",
                headers=headers[actor],
                json={"is_active": False, "reason": "Croisement"},
            )
            results[actor] = response.status_code

    try:
        threads = [
            threading.Thread(target=_remove, args=(first.id, second.id)),
            threading.Thread(target=_remove, args=(second.id, first.id)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(results.values()) in ([200, 401], [200, 409])
        with owner_engine.connect() as connection:
            active = connection.execute(
                text(
                    "SELECT count(*) FROM platform_users "
                    "WHERE role = 'administrator' AND is_active AND id = ANY(:ids)"
                ),
                {"ids": [first.id, second.id]},
            ).scalar_one()
        assert active == 1
    finally:
        _reactivate(owner_engine, [*others, first.id, second.id])


def test_platform_service_refuses_the_last_administrator_directly(
    platform_bound_to_test_database: None, owner_engine: Engine
) -> None:
    """La garde vit dans le service, pas dans l'écran : un appel direct est refusé."""
    lonely = create_platform_account("administrator")
    peer = create_platform_account("administrator")
    others = _only_active_administrators(owner_engine, {lonely.id})
    try:
        with pytest.raises(platform_service.LastAdministratorError):
            platform_service.assert_administrators_remain(excluding=lonely.id)
        platform_service.assert_administrators_remain(excluding=peer.id)
    finally:
        _reactivate(owner_engine, [*others, peer.id])


def test_support_writes_nothing_on_the_team(client: TestClient) -> None:
    support = create_platform_account("support")
    colleague = create_platform_account("support")
    headers = auth_headers(platform_login(client, support))
    assert client.get(TEAM, headers=headers).status_code == 200
    assert _invite(client, headers).status_code == 403
    assert _patch(client, headers, colleague.id, role="administrator").status_code == 403
    assert client.post(f"{INVITATIONS}/{uuid4()}/resend", headers=headers).status_code == 403
    assert client.delete(f"{INVITATIONS}/{uuid4()}", headers=headers).status_code == 403


def test_an_unknown_member_or_invitation_is_404(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    assert _patch(client, admin_headers, uuid4(), role="support").status_code == 404
    assert client.delete(f"{INVITATIONS}/{uuid4()}", headers=admin_headers).status_code == 404
    assert client.post(f"{INVITATIONS}/{uuid4()}/resend", headers=admin_headers).status_code == 404


# --------------------------------------------------------------- liste et bilan


def test_the_team_lists_members_and_pending_invitations(
    client: TestClient,
    admin_headers: dict[str, str],
    administrator: PlatformAccount,
    enqueued: list[tuple[str, dict[str, Any]]],
    smtp: list[dict[str, Any]],
) -> None:
    email = _email()
    _invite(client, admin_headers, email=email)
    team = client.get(TEAM, headers=admin_headers).json()
    assert set(team) == {"members", "invitations"}
    me = next(member for member in team["members"] if member["id"] == str(administrator.id))
    assert set(me) == {
        "id",
        "email",
        "display_name",
        "role",
        "is_active",
        "last_login_at",
        "created_at",
        "is_me",
    }
    assert me["is_me"] is True
    invitation = next(item for item in team["invitations"] if item["email"] == email)
    assert set(invitation) == {
        "id",
        "email",
        "display_name",
        "role",
        "created_at",
        "expires_at",
        "invited_by_name",
    }
    assert "password_hash" not in str(team)
    assert "token_hash" not in str(team)


def test_the_summary_counts_the_team(
    client: TestClient,
    admin_headers: dict[str, str],
    enqueued: list[tuple[str, dict[str, Any]]],
    smtp: list[dict[str, Any]],
    owner_engine: Engine,
) -> None:
    before = client.get(f"{TEAM}/summary", headers=admin_headers).json()
    assert set(before) == {
        "computed_at",
        "members",
        "active",
        "suspended",
        "pending_invitations",
        "expiring_invitations",
    }
    assert before["members"] == before["active"] + before["suspended"]
    colleague = create_platform_account("support")
    _patch(client, admin_headers, colleague.id, is_active=False, reason="Départ")
    invitation = _invite(client, admin_headers).json()["invitation"]
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE platform_invitations SET expires_at = now() + interval '3 hours' "
                "WHERE id = :id"
            ),
            {"id": invitation["id"]},
        )
    after = client.get(f"{TEAM}/summary", headers=admin_headers).json()
    assert after["members"] == before["members"] + 1
    assert after["suspended"] == before["suspended"] + 1
    assert after["pending_invitations"] == before["pending_invitations"] + 1
    assert after["expiring_invitations"] == before["expiring_invitations"] + 1


def test_a_refused_commit_changes_no_invitation_nor_member(
    client: TestClient,
    admin_headers: dict[str, str],
    enqueued: list[tuple[str, dict[str, Any]]],
    smtp: list[dict[str, Any]],
    owner_engine: Engine,
) -> None:
    """Renvoi, annulation, profil, suspension et acceptation : rien ne reste, rien ne part."""
    invitation = _invite(client, admin_headers).json()["invitation"]
    _run_send_task(enqueued)
    token = _token_from(smtp[-1])
    before = _invitation_row(owner_engine, invitation["id"])
    colleague = create_platform_account("support")
    enqueued.clear()

    with failing_platform_commit(owner_engine):
        resent = client.post(f"{INVITATIONS}/{invitation['id']}/resend", headers=admin_headers)
        revoked = client.delete(f"{INVITATIONS}/{invitation['id']}", headers=admin_headers)
        promoted = _patch(client, admin_headers, colleague.id, role="administrator")
        suspended = _patch(client, admin_headers, colleague.id, is_active=False, reason="Test")
        accepted = _accept(client, token)
    assert [r.status_code for r in (resent, revoked, promoted, suspended, accepted)] == [500] * 5
    assert enqueued == []
    after = _invitation_row(owner_engine, invitation["id"])
    assert (after.issue, after.token_hash, after.revoked_at, after.accepted_at) == (
        before.issue,
        before.token_hash,
        None,
        None,
    )
    with owner_engine.connect() as connection:
        member = connection.execute(
            text("SELECT role, is_active FROM platform_users WHERE id = :id"),
            {"id": colleague.id},
        ).one()
    assert (member.role, member.is_active) == ("support", True)
    # Le lien sert toujours.
    assert _accept(client, token).status_code == 200
