"""Double authentification obligatoire de l'administration (ADR 0105).

Enrôlement (code faux refusé, secret jamais rendu après l'activation), connexion sans code
refusée, jeton intermédiaire limité à son étape et à usage unique, rejeu du même code
refusé, codes de secours (usage unique, empreintes en base), freinage commun au mot de
passe et au code, sessions (12 h, 1 h d'inactivité), nouvel appareil signalé,
réinitialisation par un autre administrateur et jamais sur soi, CLI, journal sans secret.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.sql import text

from app import cli
from app.core import mfa, queue, rate_limit, totp
from app.core.config import Settings, get_settings
from app.core.security import ALGORITHM, PLATFORM_AUDIENCE, PLATFORM_TOKEN_TYPE
from app.main import app
from app.modules.platform import service as platform_service
from tests.conftest import TEST_BASE_URL, auth_headers
from tests.integration.platform_harness import (
    DEVICE_COOKIE,
    PLATFORM_PASSWORD,
    PlatformAccount,
    create_platform_account,
    current_code,
    failing_platform_commit,
    forget_last_code,
    password_step,
    platform_login,
    platform_login_response,
)

pytestmark = pytest.mark.integration

LOGIN = "/api/v1/platform/auth/login"
ENROLL = "/api/v1/platform/auth/mfa/enrollment"
CONFIRM = "/api/v1/platform/auth/mfa/enrollment/confirm"
VERIFY = "/api/v1/platform/auth/mfa/verify"
RECOVERY = "/api/v1/platform/auth/mfa/recovery-codes"
ME = "/api/v1/platform/auth/me"
REFRESH = "/api/v1/platform/auth/refresh"


@pytest.fixture
def administrator(platform_bound_to_test_database: None) -> PlatformAccount:
    return create_platform_account("administrator")


@pytest.fixture
def newcomer(platform_bound_to_test_database: None) -> PlatformAccount:
    """Compte d'avant ce lot, ou créé sans `--mfa-secret` : il doit enrôler."""
    return create_platform_account("support", enrolled=False)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def _record(task_name: str, **kwargs: Any) -> bool:
        calls.append((task_name, kwargs))
        return True

    monkeypatch.setattr(queue, "enqueue", _record)
    return calls


@pytest.fixture
def fresh_client() -> Any:
    """Un navigateur neuf : aucun cookie d'appareil."""
    with TestClient(app, base_url=TEST_BASE_URL) as client:
        yield client


def _row(owner_engine: Engine, account_id: UUID) -> Any:
    with owner_engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT mfa_secret, mfa_enabled_at, mfa_last_step FROM platform_users "
                "WHERE id = :id"
            ),
            {"id": account_id},
        ).one()


def _enroll(client: TestClient, account: PlatformAccount) -> tuple[str, Any]:
    """Mot de passe, secret proposé, premier code : (secret, réponse d'activation)."""
    step = password_step(client, account)
    assert step["step"] == "enroll"
    proposed = client.post(ENROLL, json={"challenge_token": step["challenge_token"]})
    assert proposed.status_code == 200, proposed.text
    secret = proposed.json()["secret"]
    activated = client.post(
        CONFIRM,
        json={
            "challenge_token": step["challenge_token"],
            "code": totp.code_at(secret, totp.current_step()),
        },
    )
    assert activated.status_code == 200, activated.text
    return secret, activated


def _audit_diffs(owner_engine: Engine, account_id: UUID) -> list[str]:
    with owner_engine.connect() as connection:
        return [
            str(row.diff)
            for row in connection.execute(
                text("SELECT diff::text AS diff FROM platform_audit_logs WHERE entity_id = :id"),
                {"id": account_id},
            )
        ]


# --------------------------------------------------------------------- enrôlement


def test_a_password_alone_opens_no_session(
    client: TestClient, administrator: PlatformAccount
) -> None:
    response = client.post(
        LOGIN, json={"email": administrator.email, "password": PLATFORM_PASSWORD}
    )
    assert response.status_code == 200
    assert set(response.json()) == {"step", "challenge_token", "expires_in"}
    assert response.json() == {**response.json(), "step": "verify", "expires_in": 300}
    assert "coges_platform_refresh" not in response.headers.get("set-cookie", "")
    # Le jeton intermédiaire n'est pas un jeton d'accès.
    challenge = response.json()["challenge_token"]
    assert client.get(ME, headers=auth_headers(challenge)).status_code == 401
    assert client.post(REFRESH).status_code == 401


def test_an_account_without_mfa_must_enroll_first(
    client: TestClient, newcomer: PlatformAccount, owner_engine: Engine
) -> None:
    step = password_step(client, newcomer)
    assert step["step"] == "enroll"
    # Le jeton d'enrôlement n'ouvre pas la vérification : aucun chemin ne contourne.
    refused = client.post(
        VERIFY, json={"challenge_token": step["challenge_token"], "code": "123456"}
    )
    assert refused.status_code == 401
    assert refused.json()["error"]["code"] == "mfa_challenge_invalid"

    proposed = client.post(ENROLL, json={"challenge_token": step["challenge_token"]})
    assert proposed.status_code == 200
    body = proposed.json()
    assert set(body) == {"secret", "otpauth_uri", "qr_svg", "account", "issuer"}
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert f"secret={body['secret']}" in body["otpauth_uri"]
    # SVG autonome : aucun script, aucune ressource chargée d'ailleurs.
    assert body["qr_svg"].startswith("<svg")
    assert "<script" not in body["qr_svg"] and "href" not in body["qr_svg"]
    # Proposé, pas actif : rien n'est écrit sur le compte avant le premier code juste.
    assert _row(owner_engine, newcomer.id).mfa_enabled_at is None


def test_a_wrong_first_code_activates_nothing(
    client: TestClient, newcomer: PlatformAccount, owner_engine: Engine
) -> None:
    step = password_step(client, newcomer)
    secret = client.post(ENROLL, json={"challenge_token": step["challenge_token"]}).json()["secret"]
    wrong = str((int(totp.code_at(secret, totp.current_step())) + 1) % 1_000_000).zfill(6)
    refused = client.post(CONFIRM, json={"challenge_token": step["challenge_token"], "code": wrong})
    assert refused.status_code == 401
    assert refused.json()["error"]["code"] == "mfa_code_invalid"
    row = _row(owner_engine, newcomer.id)
    assert row.mfa_secret is None and row.mfa_enabled_at is None
    assert "coges_platform_refresh" not in refused.headers.get("set-cookie", "")


def test_activation_opens_the_session_and_shows_ten_recovery_codes_once(
    client: TestClient,
    newcomer: PlatformAccount,
    owner_engine: Engine,
    enqueued: list[tuple[str, dict[str, Any]]],
) -> None:
    secret, activated = _enroll(client, newcomer)
    body = activated.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "recovery_codes"}
    assert len(body["recovery_codes"]) == 10
    cookies = activated.headers.get_list("set-cookie")
    assert any(c.startswith("coges_platform_refresh=") for c in cookies)
    device = next(c for c in cookies if c.startswith(f"{DEVICE_COOKIE}="))
    assert "HttpOnly" in device and "SameSite=strict" in device and "Max-Age=31536000" in device

    me = client.get(ME, headers=auth_headers(body["access_token"])).json()
    assert me["mfa_enabled_at"] is not None and me["recovery_codes_left"] == 10
    # Le secret n'est jamais rendu après l'activation, ni stocké en clair.
    assert secret not in str(me)
    row = _row(owner_engine, newcomer.id)
    assert secret.encode() not in bytes(row.mfa_secret)
    with owner_engine.connect() as connection:
        stored = (
            connection.execute(
                text("SELECT code_hash FROM platform_recovery_codes WHERE platform_user_id = :id"),
                {"id": newcomer.id},
            )
            .scalars()
            .all()
        )
    assert len(stored) == 10
    for code in body["recovery_codes"]:
        assert code.replace("-", "") not in " ".join(stored)
    # Une nouvelle connexion demande le code, plus l'enrôlement.
    assert password_step(client, newcomer)["step"] == "verify"
    assert [name for name, _ in enqueued] == [platform_service.SECURITY_NOTICE_TASK]
    assert enqueued[0][1]["kind"] == "mfa_enabled"


def test_an_enrollment_challenge_cannot_replace_an_active_secret(
    client: TestClient, administrator: PlatformAccount
) -> None:
    step = password_step(client, administrator)
    assert step["step"] == "verify"
    refused = client.post(ENROLL, json={"challenge_token": step["challenge_token"]})
    assert refused.status_code == 401
    assert refused.json()["error"]["code"] == "mfa_challenge_invalid"


# ----------------------------------------------------------------------- connexion


def test_the_code_opens_the_session(client: TestClient, administrator: PlatformAccount) -> None:
    response = platform_login_response(client, administrator)
    assert set(response.json()) == {"access_token", "token_type", "expires_in"}
    me = client.get(ME, headers=auth_headers(response.json()["access_token"]))
    assert me.status_code == 200


def test_a_challenge_serves_once_and_expires(
    client: TestClient, administrator: PlatformAccount, owner_engine: Engine
) -> None:
    forget_last_code(administrator)
    step = password_step(client, administrator)
    body = {"challenge_token": step["challenge_token"], "code": current_code(administrator)}
    assert client.post(VERIFY, json=body).status_code == 200
    forget_last_code(administrator)
    again = client.post(VERIFY, json=body)
    assert again.status_code == 401
    assert again.json()["error"]["code"] == "mfa_challenge_invalid"

    # Échu : refusé avec un code juste.
    forget_last_code(administrator)
    later = password_step(client, administrator)
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE platform_mfa_challenges SET created_at = now() - interval '10 minutes', "
                "expires_at = now() - interval '5 minutes' WHERE platform_user_id = :id "
                "AND consumed_at IS NULL"
            ),
            {"id": administrator.id},
        )
    late = client.post(
        VERIFY,
        json={"challenge_token": later["challenge_token"], "code": current_code(administrator)},
    )
    assert late.status_code == 401
    assert late.json()["error"]["code"] == "mfa_challenge_invalid"


def test_a_new_password_step_voids_the_previous_challenge(
    client: TestClient, administrator: PlatformAccount
) -> None:
    first = password_step(client, administrator)
    password_step(client, administrator)
    forget_last_code(administrator)
    refused = client.post(
        VERIFY,
        json={"challenge_token": first["challenge_token"], "code": current_code(administrator)},
    )
    assert refused.status_code == 401


def test_the_same_code_is_refused_the_second_time(
    client: TestClient, administrator: PlatformAccount
) -> None:
    forget_last_code(administrator)
    code = current_code(administrator)
    first = password_step(client, administrator)
    assert (
        client.post(VERIFY, json={"challenge_token": first["challenge_token"], "code": code})
    ).status_code == 200
    second = password_step(client, administrator)
    replay = client.post(VERIFY, json={"challenge_token": second["challenge_token"], "code": code})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "mfa_code_invalid"


def test_a_token_without_the_second_factor_opens_nothing(
    client: TestClient, administrator: PlatformAccount
) -> None:
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": str(administrator.id),
            "platform_role": "administrator",
            "amr": ["pwd"],
            "typ": PLATFORM_TOKEN_TYPE,
            "aud": PLATFORM_AUDIENCE,
            "jti": "00000000-0000-0000-0000-000000000001",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        get_settings().jwt_secret.get_secret_value(),
        algorithm=ALGORITHM,
    )
    assert client.get(ME, headers=auth_headers(forged)).status_code == 401


# ---------------------------------------------------------------- codes de secours


def test_a_recovery_code_serves_once_and_is_reported(
    client: TestClient,
    newcomer: PlatformAccount,
    owner_engine: Engine,
    enqueued: list[tuple[str, dict[str, Any]]],
) -> None:
    _, activated = _enroll(client, newcomer)
    code = activated.json()["recovery_codes"][3]
    enqueued.clear()

    step = password_step(client, newcomer)
    used = client.post(
        VERIFY, json={"challenge_token": step["challenge_token"], "recovery_code": code.lower()}
    )
    assert used.status_code == 200, used.text
    me = client.get(ME, headers=auth_headers(used.json()["access_token"])).json()
    assert me["recovery_codes_left"] == 9
    assert "recovery_code_used" in [kwargs["kind"] for _, kwargs in enqueued]

    step = password_step(client, newcomer)
    again = client.post(
        VERIFY, json={"challenge_token": step["challenge_token"], "recovery_code": code}
    )
    assert again.status_code == 401
    assert again.json()["error"]["code"] == "mfa_code_invalid"

    diffs = _audit_diffs(owner_engine, newcomer.id)
    assert any('"method": "recovery_code"' in diff for diff in diffs)


def test_regenerating_needs_a_code_and_voids_the_old_codes(
    client: TestClient, newcomer: PlatformAccount
) -> None:
    secret, activated = _enroll(client, newcomer)
    headers = auth_headers(activated.json()["access_token"])
    old = activated.json()["recovery_codes"]

    wrong = client.post(RECOVERY, headers=headers, json={"code": "000000"})
    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "mfa_code_invalid"
    regenerated = client.post(
        RECOVERY,
        headers=headers,
        json={"code": totp.code_at(secret, totp.current_step() + 1)},
    )
    assert regenerated.status_code == 200, regenerated.text
    new = regenerated.json()["recovery_codes"]
    assert len(new) == 10 and not set(new) & set(old)

    step = password_step(client, newcomer)
    refused = client.post(
        VERIFY, json={"challenge_token": step["challenge_token"], "recovery_code": old[0]}
    )
    assert refused.status_code == 401
    accepted = client.post(
        VERIFY, json={"challenge_token": step["challenge_token"], "recovery_code": new[0]}
    )
    assert accepted.status_code == 200


# ------------------------------------------------------------------------ freinage


@pytest.fixture
def throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(
        update={
            "login_throttle_free_failures": 5,
            "login_throttle_window_minutes": 15,
            "login_throttle_max_wait_minutes": 30,
            "login_throttle_alert_after": 10,
            "rate_limit_login_per_minute": 0,
        }
    )
    monkeypatch.setattr(rate_limit, "get_settings", lambda: settings)
    monkeypatch.setattr(platform_service, "get_settings", lambda: settings)


@pytest.mark.usefixtures("throttle")
def test_wrong_codes_are_throttled_like_wrong_passwords(
    client: TestClient, administrator: PlatformAccount
) -> None:
    step = password_step(client, administrator)
    for _ in range(5):
        wrong = client.post(
            VERIFY, json={"challenge_token": step["challenge_token"], "code": "000000"}
        )
        assert wrong.status_code == 401
    forget_last_code(administrator)
    blocked = client.post(
        VERIFY,
        json={"challenge_token": step["challenge_token"], "code": current_code(administrator)},
    )
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"]
    # Le même compteur freine le mot de passe : la réponse ne dit pas lequel a échoué.
    password = client.post(
        LOGIN, json={"email": administrator.email, "password": PLATFORM_PASSWORD}
    )
    assert password.status_code == 429
    assert password.json() == blocked.json()


@pytest.mark.usefixtures("throttle")
def test_password_and_code_failures_share_one_counter(
    client: TestClient, administrator: PlatformAccount
) -> None:
    for _ in range(3):
        refused = client.post(LOGIN, json={"email": administrator.email, "password": "x" * 12})
        assert refused.status_code == 401
    # Le mot de passe juste ne remet pas le compteur à zéro : seul le code le fait.
    step = password_step(client, administrator)
    for _ in range(2):
        client.post(VERIFY, json={"challenge_token": step["challenge_token"], "code": "000000"})
    assert (
        client.post(LOGIN, json={"email": administrator.email, "password": PLATFORM_PASSWORD})
    ).status_code == 429


@pytest.mark.usefixtures("throttle")
def test_a_good_code_clears_the_counter(client: TestClient, administrator: PlatformAccount) -> None:
    step = password_step(client, administrator)
    for _ in range(4):
        client.post(VERIFY, json={"challenge_token": step["challenge_token"], "code": "000000"})
    forget_last_code(administrator)
    assert (
        client.post(
            VERIFY,
            json={"challenge_token": step["challenge_token"], "code": current_code(administrator)},
        )
    ).status_code == 200
    for _ in range(4):
        assert (
            client.post(LOGIN, json={"email": administrator.email, "password": "x" * 12})
        ).status_code == 401


# ------------------------------------------------------------------------ sessions


def _age_session(owner_engine: Engine, account_id: UUID, column: str, hours: float) -> None:
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE platform_auth_sessions SET {column} = now() - make_interval(secs => :s) "  # noqa: S608
                "WHERE platform_user_id = :id AND revoked_at IS NULL"
            ),
            {"id": account_id, "s": hours * 3600},
        )


def test_a_session_idle_for_an_hour_is_refused(
    client: TestClient, administrator: PlatformAccount, owner_engine: Engine
) -> None:
    platform_login(client, administrator)
    assert client.post(REFRESH).status_code == 200
    _age_session(owner_engine, administrator.id, "issued_at", 1.1)
    assert client.post(REFRESH).status_code == 401


def test_a_session_ends_after_twelve_hours_even_when_active(
    client: TestClient, administrator: PlatformAccount, owner_engine: Engine
) -> None:
    response = platform_login_response(client, administrator)
    cookie = next(
        c for c in response.headers.get_list("set-cookie") if c.startswith("coges_platform_refresh")
    )
    assert "Max-Age=43200" in cookie
    _age_session(owner_engine, administrator.id, "authenticated_at", 12.1)
    assert client.post(REFRESH).status_code == 401


# ------------------------------------------------------------------ nouvel appareil


def test_a_new_device_is_reported_and_a_known_one_is_not(
    fresh_client: TestClient,
    newcomer: PlatformAccount,
    owner_engine: Engine,
    enqueued: list[tuple[str, dict[str, Any]]],
    administrator: PlatformAccount,
) -> None:
    secret, _ = _enroll(fresh_client, newcomer)
    enqueued.clear()
    # Même navigateur, même cookie : appareil connu.
    step = password_step(fresh_client, newcomer)
    known = fresh_client.post(
        VERIFY,
        json={
            "challenge_token": step["challenge_token"],
            "code": totp.code_at(secret, totp.current_step() + 1),
        },
    )
    assert known.status_code == 200
    assert enqueued == []

    # Un autre navigateur (aucun cookie) : signalé, au journal et dans « À traiter ».
    with TestClient(
        app,
        base_url=TEST_BASE_URL,
        headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0) Firefox/140.0"},
    ) as other:
        with owner_engine.begin() as connection:
            connection.execute(
                text("UPDATE platform_users SET mfa_last_step = NULL WHERE id = :id"),
                {"id": newcomer.id},
            )
        step = password_step(other, newcomer)
        fresh = other.post(
            VERIFY,
            json={
                "challenge_token": step["challenge_token"],
                "code": totp.code_at(secret, totp.current_step()),
            },
        )
        assert fresh.status_code == 200
    assert [kwargs for _, kwargs in enqueued] == [
        {
            "countdown": 0,
            "platform_user_id": str(newcomer.id),
            "kind": "new_device",
            "device": "Firefox · Windows",
        }
    ]
    attention = fresh_client.get(
        "/api/v1/platform/attention",
        headers=auth_headers(platform_login(fresh_client, administrator)),
    ).json()
    events = [e for e in attention["security_events"] if e["platform_user_id"] == str(newcomer.id)]
    assert {e["kind"] for e in events} == {"new_device", "mfa_enabled"}
    assert next(e for e in events if e["kind"] == "new_device")["device"] == "Firefox · Windows"


# ---------------------------------------------------------------- réinitialisation


def test_another_administrator_resets_a_lost_phone(
    client: TestClient,
    administrator: PlatformAccount,
    owner_engine: Engine,
    enqueued: list[tuple[str, dict[str, Any]]],
) -> None:
    colleague = create_platform_account("support")
    with TestClient(app, base_url=TEST_BASE_URL) as theirs:
        their_token = platform_login(theirs, colleague)
        assert theirs.get(ME, headers=auth_headers(their_token)).status_code == 200

        admin_headers = auth_headers(platform_login(client, administrator))
        enqueued.clear()
        reset = client.post(
            f"/api/v1/platform/team/{colleague.id}/mfa-reset",
            headers=admin_headers,
            json={"reason": "Téléphone perdu"},
        )
        assert reset.status_code == 200, reset.text
        assert reset.json()["mfa_enabled"] is False

        # Jeton d'accès refusé tout de suite, session de rafraîchissement fermée.
        assert theirs.get(ME, headers=auth_headers(their_token)).status_code == 401
        assert theirs.post(REFRESH).status_code == 401
        # Réenrôlement forcé à la connexion suivante.
        assert password_step(theirs, colleague)["step"] == "enroll"

    row = _row(owner_engine, colleague.id)
    assert row.mfa_secret is None and row.mfa_enabled_at is None
    with owner_engine.connect() as connection:
        live_codes = connection.execute(
            text(
                "SELECT count(*) FROM platform_recovery_codes WHERE platform_user_id = :id "
                "AND used_at IS NULL AND revoked_at IS NULL"
            ),
            {"id": colleague.id},
        ).scalar_one()
    assert live_codes == 0
    assert [kwargs["kind"] for _, kwargs in enqueued] == ["mfa_reset"]
    assert any('"reason": "Téléphone perdu"' in d for d in _audit_diffs(owner_engine, colleague.id))


def test_nobody_resets_their_own_mfa_and_support_resets_nobody(
    client: TestClient, administrator: PlatformAccount
) -> None:
    headers = auth_headers(platform_login(client, administrator))
    own = client.post(
        f"/api/v1/platform/team/{administrator.id}/mfa-reset",
        headers=headers,
        json={"reason": "Essai"},
    )
    assert own.status_code == 409
    assert own.json()["error"]["code"] == "cannot_reset_own_mfa"

    support = create_platform_account("support")
    with TestClient(app, base_url=TEST_BASE_URL) as theirs:
        refused = theirs.post(
            f"/api/v1/platform/team/{administrator.id}/mfa-reset",
            headers=auth_headers(platform_login(theirs, support)),
            json={"reason": "Essai"},
        )
    assert refused.status_code == 403


def test_the_cli_resets_mfa_as_a_last_resort(
    client: TestClient, administrator: PlatformAccount, capsys: pytest.CaptureFixture[str]
) -> None:
    platform_login(client, administrator)
    assert cli.main(["reset-platform-mfa", "--email", administrator.email]) == 0
    assert "réinitialisée" in capsys.readouterr().out
    assert client.post(REFRESH).status_code == 401
    assert password_step(client, administrator)["step"] == "enroll"
    assert cli.main(["reset-platform-mfa", "--email", "personne@exemple.com"]) == 1


def test_a_known_secret_is_refused_outside_local_and_ci(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for env in ("staging", "production"):
        settings = Settings(_env_file=None, env=env, jwt_secret="x" * 40)  # type: ignore[call-arg, arg-type]
        monkeypatch.setattr(platform_service, "get_settings", lambda s=settings: s)
        with pytest.raises(platform_service.MfaSecretOutsideDevelopmentError):
            platform_service.create_platform_user(
                email="e2e@exemple.com",
                display_name="E2E",
                role="administrator",
                password=PLATFORM_PASSWORD,
                mfa_secret=totp.generate_secret(),
            )
        code = cli.main(
            [
                "create-platform-user",
                "--email",
                "e2e@exemple.com",
                "--name",
                "E2E",
                "--role",
                "administrator",
                "--password",
                PLATFORM_PASSWORD,
                "--mfa-secret",
                totp.generate_secret(),
            ]
        )
        assert code == 2
        assert "local et en CI" in capsys.readouterr().err


# ------------------------------------------------------------------ journal, COMMIT


def test_the_journal_never_holds_a_secret_or_a_code(
    client: TestClient, newcomer: PlatformAccount, owner_engine: Engine
) -> None:
    secret, activated = _enroll(client, newcomer)
    codes = activated.json()["recovery_codes"]
    step = password_step(client, newcomer)
    client.post(
        VERIFY, json={"challenge_token": step["challenge_token"], "recovery_code": codes[0]}
    )
    journal = " ".join(_audit_diffs(owner_engine, newcomer.id))
    assert secret not in journal
    for code in codes:
        assert code not in journal and code.replace("-", "") not in journal
    assert step["challenge_token"] not in journal


def test_a_refused_commit_keeps_mfa_unchanged(
    administrator: PlatformAccount,
    owner_engine: Engine,
    enqueued: list[tuple[str, dict[str, Any]]],
    platform_bound_to_test_database: None,
) -> None:
    newcomer = create_platform_account("support", enrolled=False)
    colleague = create_platform_account("support")
    with TestClient(app, base_url=TEST_BASE_URL, raise_server_exceptions=False) as raw:
        admin_headers = auth_headers(platform_login(raw, administrator))
        enqueued.clear()
        step = password_step(raw, newcomer)
        secret = raw.post(ENROLL, json={"challenge_token": step["challenge_token"]}).json()[
            "secret"
        ]
        with failing_platform_commit(owner_engine):
            confirm = raw.post(
                CONFIRM,
                json={
                    "challenge_token": step["challenge_token"],
                    "code": totp.code_at(secret, totp.current_step()),
                },
            )
            forget_last_code(administrator)
            verify_step = password_step(raw, administrator)
            verify = raw.post(
                VERIFY,
                json={
                    "challenge_token": verify_step["challenge_token"],
                    "code": current_code(administrator),
                },
            )
            regenerate = raw.post(
                RECOVERY,
                headers=admin_headers,
                json={"code": totp.code_at(str(administrator.mfa_secret), totp.current_step() + 1)},
            )
            reset = raw.post(
                f"/api/v1/platform/team/{colleague.id}/mfa-reset",
                headers=admin_headers,
                json={"reason": "Téléphone perdu"},
            )
    assert [r.status_code for r in (confirm, verify, regenerate, reset)] == [500] * 4
    assert _row(owner_engine, newcomer.id).mfa_enabled_at is None
    assert _row(owner_engine, colleague.id).mfa_enabled_at is not None
    assert enqueued == []
    with owner_engine.connect() as connection:
        sessions = connection.execute(
            text("SELECT count(*) FROM platform_auth_sessions WHERE platform_user_id = :id"),
            {"id": newcomer.id},
        ).scalar_one()
    assert sessions == 0
    assert mfa.PLATFORM_MFA_REQUIRED
