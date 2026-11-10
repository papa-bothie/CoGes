"""Inscription libre-service (lot 30, ADR 0118).

Une demande n'est pas une boutique : rien n'existe chez les commerçants avant
l'activation, par le lien e-mail ou par l'équipe, toutes deux passant par la même
fonction. Les réponses publiques sont neutres ; les jetons et l'IP ne sont stockés
qu'en empreinte ; Redis indisponible ferme la porte.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.sql import text

from app.core import cache, deps, legal, mailer, queue
from app.core.config import get_settings
from app.main import app
from app.modules.signup import limits
from app.modules.signup import router as signup_router
from app.modules.signup import service as signup_service
from app.workers.tasks import signup as signup_tasks
from tests.conftest import TEST_BASE_URL, auth_headers
from tests.integration.platform_harness import (
    PlatformAccount,
    create_platform_account,
    platform_login,
)

pytestmark = pytest.mark.integration

CREATE = "/api/v1/auth/signup-requests"
VERIFY = "/api/v1/auth/signup-requests/verify"
RESEND = "/api/v1/auth/signup-requests/resend"
CONTACT = "/api/v1/auth/signup-requests/contact-team"
CONFIG = "/api/v1/auth/signup-config"
ADMIN = "/api/v1/platform/signup-requests"
PASSWORD = "-".join(("mon", "mot", "de", "passe", "2026"))


def _settings(monkeypatch: pytest.MonkeyPatch, **update: Any) -> None:
    """Réglages de l'inscription, posés partout où ils sont lus."""
    base = {
        "signup_enabled": True,
        "smtp_host": "smtp.example.com",
        "signup_global_per_hour": 10_000,
        "signup_auto_per_day": 10_000,
        "signup_ip_per_hour": 10_000,
        "signup_ip_per_day": 10_000,
        "platform_alert_email": "equipe@coges.example.com",
    }
    patched = get_settings().model_copy(update={**base, **update})
    for module in (signup_service, limits, signup_router, mailer, signup_tasks):
        monkeypatch.setattr(module, "get_settings", lambda: patched)


@pytest.fixture
def signup_on(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)


@pytest.fixture(autouse=True)
def clean_signup_keys() -> Iterator[None]:
    client = cache.get_client()
    if client is not None:
        for key in client.scan_iter("coges:signup:*"):
            client.delete(key)
    yield


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def _record(task_name: str, **kwargs: Any) -> bool:
        calls.append((task_name, kwargs))
        return True

    monkeypatch.setattr(queue, "enqueue", _record)
    return calls


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """E-mails « envoyés » par le worker : capturés, jamais remis à un SMTP."""
    outbox: list[dict[str, Any]] = []

    def _send(*, to: list[str], subject: str, body: str, html: str | None = None) -> bool:
        outbox.append({"to": to, "subject": subject, "body": body, "html": html})
        return True

    monkeypatch.setattr(mailer, "send_email", _send)
    return outbox


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


def _phone() -> str:
    """Un numéro neuf, tapé comme un commerçant le tape."""
    digits = f"7{uuid4().int % 10**8:08d}"
    return f"{digits[:2]} {digits[2:5]} {digits[5:7]} {digits[7:]}"


def _form(**update: Any) -> dict[str, Any]:
    return {
        "shop_name": "Boutique Awa",
        "full_name": "Awa Ndiaye",
        "phone": _phone(),
        "email": f"awa-{uuid4().hex[:8]}@example.com",
        "password": PASSWORD,
        "accept_legal": True,
        **update,
    }


def _owner_rows(owner_engine: Engine, sql: str, **params: Any) -> list[Any]:
    with owner_engine.connect() as connection:
        return list(connection.execute(text(sql), params).all())


def _request(owner_engine: Engine, *, phone_e164: str) -> Any:
    rows = _owner_rows(
        owner_engine,
        "SELECT * FROM signup_requests WHERE phone = :phone ORDER BY created_at DESC",
        phone=phone_e164,
    )
    return rows[0] if rows else None


def _e164(typed: str) -> str:
    return "+221" + "".join(ch for ch in typed if ch.isdigit())


def _platform_rows(sql: str, **params: Any) -> list[Any]:
    """Lecture sous `coges_app_platform` (la RLS FORCE masque tout au propriétaire)."""
    with deps.platform_transaction() as session:
        return list(session.execute(text(sql), params).all())


def _companies_named(owner_engine: Engine, name: str) -> int:
    del owner_engine
    rows = _platform_rows("SELECT count(*) AS n FROM companies WHERE name = :name", name=name)
    return int(rows[0].n)


def _verification_token(
    enqueued: list[tuple[str, dict[str, Any]]], sent: list[dict[str, Any]]
) -> str:
    """Joue la tâche du worker comme il le ferait, et lit le jeton dans l'e-mail."""
    request_id = next(
        kwargs["request_id"]
        for name, kwargs in enqueued
        if name == signup_service.SEND_VERIFICATION_TASK
    )
    sent.clear()
    assert signup_tasks.send_verification.run(request_id) is True
    link = next(line for line in sent[-1]["body"].splitlines() if "/verification/" in line)
    return link.rsplit("/", 1)[-1].strip()


# --- Interrupteur -----------------------------------------------------------------------


def test_switched_off_every_public_route_is_404_and_nothing_is_written(
    client: TestClient, owner_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _settings(monkeypatch, signup_enabled=False)
    form = _form()
    for path, body in (
        (CREATE, form),
        (VERIFY, {"token": "x" * 43}),
        (RESEND, {"email": form["email"]}),
        (CONTACT, {"email": form["email"]}),
    ):
        assert client.post(path, json=body).status_code == 404, path
    assert _request(owner_engine, phone_e164=_e164(form["phone"])) is None
    config = client.get(CONFIG).json()
    assert config["enabled"] is False
    assert config["instant_with_email"] is False


# --- Chemin e-mail ----------------------------------------------------------------------


def test_email_path_from_request_to_login_by_email_and_by_phone(
    client: TestClient,
    owner_engine: Engine,
    signup_on: None,
    enqueued: list[tuple[str, dict[str, Any]]],
    sent: list[dict[str, Any]],
) -> None:
    form = _form(shop_name=f"Épicerie Awa {uuid4().hex[:4]}")
    response = client.post(CREATE, json=form)
    assert response.status_code == 202, response.text
    assert response.json() == {"path": "email", "message": signup_service.MESSAGE_EMAIL}

    row = _request(owner_engine, phone_e164=_e164(form["phone"]))
    assert row.status == "pending" and row.path == "email"
    assert row.legal_version == legal.LEGAL_VERSION
    assert row.password_hash.startswith("$argon2") and PASSWORD not in row.password_hash
    # Rien chez les commerçants avant l'activation : ni entreprise, ni essai.
    assert _companies_named(owner_engine, form["shop_name"]) == 0

    token = _verification_token(enqueued, sent)
    assert sent[-1]["to"] == [form["email"]]
    assert "si ce n'est pas vous" in sent[-1]["body"].lower()
    assert sent[-1]["html"] and token in sent[-1]["html"]
    # Le jeton n'est stocké qu'en empreinte.
    hashes = _owner_rows(
        owner_engine,
        "SELECT token_hash FROM signup_email_tokens WHERE request_id = :id",
        id=row.id,
    )
    assert [h.token_hash for h in hashes] == [hashlib.sha256(token.encode()).hexdigest()]

    verified = client.post(VERIFY, json={"token": token})
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["status"] == "ready"
    slug = body["company_slug"]
    assert slug.startswith("epicerie-awa")

    row = _request(owner_engine, phone_e164=_e164(form["phone"]))
    assert row.status == "activated" and row.decided_via == "email_link"
    assert row.email_verified_at is not None and row.activated_company_id is not None
    # Essai de 30 jours, né avec l'entreprise (ADR 0091).
    trial = _platform_rows(
        "SELECT status, trial_ends_at FROM subscriptions WHERE company_id = :id",
        id=row.activated_company_id,
    )[0]
    audit = _platform_rows(
        "SELECT diff FROM platform_audit_logs WHERE entity_table = 'signup_requests' "
        "AND entity_id = :id",
        id=row.id,
    )
    assert trial.status == "trial"
    assert audit and audit[0].diff["after"] == {"status": "activated", "via": "email_link"}
    # Bienvenue après le COMMIT, à l'adresse vérifiée.
    assert any(name == signup_service.WELCOME_TASK for name, _ in enqueued)

    for identifier in (form["email"], form["phone"]):
        login = client.post(
            "/api/v1/auth/login",
            json={"company_slug": slug, "identifier": identifier, "password": PASSWORD},
        )
        assert login.status_code == 200, (identifier, login.text)
    me = client.get("/api/v1/auth/me", headers=auth_headers(login.json()["access_token"])).json()
    assert me["user"]["must_change_password"] is False
    # L'acceptation de la case est déjà enregistrée sur le gérant.
    assert me["user"]["must_accept_legal"] is False
    assert {role["name"] for role in me["roles"]} == {"gerant"}


def test_a_used_unknown_or_expired_link_gets_one_answer(
    client: TestClient,
    owner_engine: Engine,
    signup_on: None,
    enqueued: list[tuple[str, dict[str, Any]]],
    sent: list[dict[str, Any]],
) -> None:
    form = _form()
    client.post(CREATE, json=form)
    token = _verification_token(enqueued, sent)
    assert client.post(VERIFY, json={"token": token}).status_code == 200

    expected = None
    for candidate in (token, "inconnu-" + "x" * 40):
        answer = client.post(VERIFY, json={"token": candidate})
        assert answer.status_code == 400
        expected = expected or answer.json()
        assert answer.json() == expected
    assert expected["error"]["code"] == "signup_link_invalid"

    # Expiré : même réponse, rien de créé.
    other = _form()
    enqueued.clear()
    client.post(CREATE, json=other)
    stale = _verification_token(enqueued, sent)
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE signup_email_tokens SET expires_at = now() - interval '1 minute' "
                "WHERE token_hash = :hash"
            ),
            {"hash": hashlib.sha256(stale.encode()).hexdigest()},
        )
    assert client.post(VERIFY, json={"token": stale}).json() == expected
    assert _request(owner_engine, phone_e164=_e164(other["phone"])).status == "pending"


def test_a_new_link_makes_the_old_one_useless(
    client: TestClient,
    owner_engine: Engine,
    signup_on: None,
    enqueued: list[tuple[str, dict[str, Any]]],
    sent: list[dict[str, Any]],
) -> None:
    form = _form()
    client.post(CREATE, json=form)
    first = _verification_token(enqueued, sent)
    enqueued.clear()
    assert client.post(RESEND, json={"email": form["email"]}).status_code == 202
    second = _verification_token(enqueued, sent)
    assert first != second
    assert client.post(VERIFY, json={"token": first}).status_code == 400
    assert client.post(VERIFY, json={"token": second}).json()["status"] == "ready"


def test_resend_is_neutral_and_limited(
    client: TestClient, signup_on: None, enqueued: list[tuple[str, dict[str, Any]]]
) -> None:
    unknown = client.post(RESEND, json={"email": f"personne-{uuid4().hex[:6]}@example.com"})
    assert unknown.status_code == 202
    form = _form()
    client.post(CREATE, json=form)
    known = client.post(RESEND, json={"email": form["email"]})
    assert known.status_code == 202 and known.json() == unknown.json()
    # Une minute entre deux renvois.
    again = client.post(RESEND, json={"email": form["email"]})
    assert again.status_code == 429
    assert again.headers["Retry-After"] == str(get_settings().signup_resend_interval_seconds)


# --- Chemin de l'équipe -----------------------------------------------------------------


def test_team_path_without_email_then_activation_and_login_by_phone(
    client: TestClient,
    owner_engine: Engine,
    signup_on: None,
    enqueued: list[tuple[str, dict[str, Any]]],
    admin_headers: dict[str, str],
) -> None:
    form = _form(email=None, shop_name=f"Quincaillerie {uuid4().hex[:4]}")
    response = client.post(CREATE, json=form)
    assert response.json() == {"path": "team", "message": signup_service.MESSAGE_TEAM}
    assert [name for name, _ in enqueued] == [signup_service.NOTIFY_TEAM_TASK]
    row = _request(owner_engine, phone_e164=_e164(form["phone"]))

    page = client.get(f"{ADMIN}?status=pending&path=team", headers=admin_headers).json()
    assert page["team_queue"] >= 1
    item = next(item for item in page["items"] if item["id"] == str(row.id))
    assert item["phone"] == _e164(form["phone"]) and item["email"] is None
    assert "password_hash" not in item and "ip_hash" not in item

    activated = client.post(f"{ADMIN}/{row.id}/activate", headers=admin_headers)
    assert activated.status_code == 200, activated.text
    slug = activated.json()["company_slug"]
    assert activated.json()["status"] == "activated"
    assert activated.json()["decided_via"] == "team"
    # Pas d'e-mail vérifié : pas de bienvenue par e-mail (l'équipe envoie l'accès sur WhatsApp).
    assert signup_service.WELCOME_TASK not in [name for name, _ in enqueued]

    login = client.post(
        "/api/v1/auth/login",
        json={"company_slug": slug, "identifier": form["phone"], "password": PASSWORD},
    )
    assert login.status_code == 200, login.text

    # Deuxième activation : refusée, une seule boutique.
    twice = client.post(f"{ADMIN}/{row.id}/activate", headers=admin_headers)
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "signup_not_pending"
    assert _companies_named(owner_engine, form["shop_name"]) == 1


def test_without_smtp_an_email_request_goes_to_the_team_without_error(
    client: TestClient,
    owner_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[tuple[str, dict[str, Any]]],
) -> None:
    _settings(monkeypatch, smtp_host=None)
    assert client.get(CONFIG).json()["instant_with_email"] is False
    form = _form()
    response = client.post(CREATE, json=form)
    assert response.status_code == 202
    assert response.json()["path"] == "team"
    assert _request(owner_engine, phone_e164=_e164(form["phone"])).path == "team"
    assert signup_service.SEND_VERIFICATION_TASK not in [name for name, _ in enqueued]


def test_a_disposable_address_goes_to_the_team(
    client: TestClient, owner_engine: Engine, signup_on: None, enqueued: list[Any]
) -> None:
    form = _form(email=f"x{uuid4().hex[:6]}@yopmail.com")
    assert client.post(CREATE, json=form).json()["path"] == "team"
    assert _request(owner_engine, phone_e164=_e164(form["phone"])).path == "team"


def test_no_email_received_moves_the_request_to_the_team(
    client: TestClient, owner_engine: Engine, signup_on: None, enqueued: list[Any]
) -> None:
    form = _form()
    client.post(CREATE, json=form)
    assert client.post(CONTACT, json={"email": form["email"]}).status_code == 202
    row = _request(owner_engine, phone_e164=_e164(form["phone"]))
    assert row.path == "team" and row.path_changed_at is not None


# --- Neutralité et doublons -------------------------------------------------------------


def test_answers_are_identical_whether_known_pending_or_new(
    client: TestClient,
    owner_engine: Engine,
    signup_on: None,
    enqueued: list[tuple[str, dict[str, Any]]],
    sent: list[dict[str, Any]],
) -> None:
    # Un compte existant (e-mail et numéro), créé par une première inscription.
    first = _form()
    client.post(CREATE, json=first)
    client.post(VERIFY, json={"token": _verification_token(enqueued, sent)})

    new = client.post(CREATE, json=_form()).json()
    pending_form = _form()
    client.post(CREATE, json=pending_form)
    pending_again = client.post(CREATE, json={**pending_form, "shop_name": "Autre"}).json()
    enqueued.clear()
    known_email = client.post(CREATE, json=_form(email=first["email"])).json()
    assert new == pending_again == known_email

    # L'adresse déjà inscrite reçoit l'e-mail qui le dit, et aucune demande ne naît.
    assert [name for name, _ in enqueued] == [signup_service.ALREADY_REGISTERED_TASK]
    signup_tasks.already_registered.run(first["email"])
    assert "déjà un compte" in sent[-1]["body"]
    count = _owner_rows(
        owner_engine,
        "SELECT count(*) AS n FROM signup_requests WHERE email = :email",
        email=first["email"],
    )[0].n
    assert count == 1
    # Une seconde demande avec le même numéro en attente rend la première, sans doublon.
    assert (
        len(
            _owner_rows(
                owner_engine,
                "SELECT id FROM signup_requests WHERE phone = :phone",
                phone=_e164(pending_form["phone"]),
            )
        )
        == 1
    )

    team_new = client.post(CREATE, json=_form(email=None)).json()
    team_known_phone = client.post(CREATE, json=_form(email=None, phone=first["phone"])).json()
    assert team_new == team_known_phone


def test_a_known_phone_never_opens_a_second_shop_by_itself(
    client: TestClient,
    owner_engine: Engine,
    signup_on: None,
    enqueued: list[tuple[str, dict[str, Any]]],
    sent: list[dict[str, Any]],
    admin_headers: dict[str, str],
) -> None:
    first = _form()
    client.post(CREATE, json=first)
    client.post(VERIFY, json={"token": _verification_token(enqueued, sent)})
    # Même numéro, écrit autrement, nouvelle adresse : le lien vérifie, mais n'active pas.
    digits = "".join(ch for ch in first["phone"] if ch.isdigit())
    enqueued.clear()
    second = _form(phone=f"00221 {digits}")
    client.post(CREATE, json=second)
    answer = client.post(VERIFY, json={"token": _verification_token(enqueued, sent)}).json()
    assert answer["status"] == "team"
    row = _request(owner_engine, phone_e164=_e164(first["phone"]))
    assert row.status == "pending" and row.path == "team" and row.email_verified_at is not None
    detail = client.get(f"{ADMIN}/{row.id}", headers=admin_headers).json()
    assert detail["known_accounts"] and detail["known_accounts"][0]["matched_on"] == "phone"


def test_the_honeypot_writes_nothing(
    client: TestClient, owner_engine: Engine, signup_on: None, enqueued: list[Any]
) -> None:
    form = _form(website="http://spam.example")
    assert client.post(CREATE, json=form).json()["path"] == "email"
    assert _request(owner_engine, phone_e164=_e164(form["phone"])) is None
    assert enqueued == []


def test_the_form_is_strict(client: TestClient, signup_on: None) -> None:
    for broken in (
        _form(accept_legal=False),
        _form(password="court"),
        _form(phone="12"),
        {**_form(), "legal_version": "2000-01-01"},
        {**_form(), "company_slug": "imposé"},
    ):
        assert client.post(CREATE, json=broken).status_code == 422, broken


# --- Connexion avant l'activation -------------------------------------------------------


def test_login_with_a_pending_request_says_so_only_with_the_right_password(
    client: TestClient, signup_on: None, enqueued: list[Any]
) -> None:
    email_form = _form()
    client.post(CREATE, json=email_form)
    team_form = _form(email=None)
    client.post(CREATE, json=team_form)

    def login(identifier: str, password: str) -> Any:
        return client.post(
            "/api/v1/auth/login",
            json={"company_slug": "nimporte", "identifier": identifier, "password": password},
        )

    wrong = login(email_form["email"], "pas-le-bon-mot-2026")
    assert wrong.status_code == 401
    assert login("inconnu@example.com", PASSWORD).json() == wrong.json()

    by_email = login(email_form["email"], PASSWORD)
    assert by_email.status_code == 403 and "refresh" not in by_email.cookies
    assert by_email.json()["error"]["code"] == "signup_email_pending"
    by_phone = login(team_form["phone"], PASSWORD)
    assert by_phone.json()["error"]["code"] == "signup_team_pending"
    assert "access_token" not in by_phone.json()


# --- Concurrence, échec au COMMIT -------------------------------------------------------


def test_link_and_team_at_the_same_time_open_one_shop(
    client: TestClient,
    owner_engine: Engine,
    signup_on: None,
    enqueued: list[tuple[str, dict[str, Any]]],
    sent: list[dict[str, Any]],
    administrator: PlatformAccount,
) -> None:
    form = _form(shop_name=f"Course {uuid4().hex[:4]}")
    client.post(CREATE, json=form)
    token = _verification_token(enqueued, sent)
    row = _request(owner_engine, phone_e164=_e164(form["phone"]))
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def by_link() -> None:
        barrier.wait()
        try:
            signup_service.verify(token, ip_address=None)
            outcomes.append("link")
        except Exception as exc:
            outcomes.append(type(exc).__name__)

    def by_team() -> None:
        barrier.wait()
        try:
            signup_service.activate_request(
                row.id, actor=administrator.id, via="team", ip_address=None
            )
            outcomes.append("team")
        except Exception as exc:
            outcomes.append(type(exc).__name__)

    threads = [threading.Thread(target=by_link), threading.Thread(target=by_team)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) in (
        ["SignupNotPendingError", "link"],
        ["SignupLinkInvalidError", "team"],
    ), outcomes
    assert _companies_named(owner_engine, form["shop_name"]) == 1


def test_a_refused_commit_creates_nothing_and_sends_nothing(
    client: TestClient,
    owner_engine: Engine,
    signup_on: None,
    enqueued: list[tuple[str, dict[str, Any]]],
    sent: list[dict[str, Any]],
) -> None:
    form = _form(shop_name=f"Échec {uuid4().hex[:4]}")
    client.post(CREATE, json=form)
    token = _verification_token(enqueued, sent)
    enqueued.clear()
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE FUNCTION test_signup_fail() RETURNS trigger LANGUAGE plpgsql AS "
                "$$ BEGIN RAISE EXCEPTION 'COMMIT refusé (test)'; END $$"
            )
        )
        connection.execute(
            text(
                "CREATE CONSTRAINT TRIGGER test_signup_fail AFTER UPDATE ON signup_requests "
                "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION test_signup_fail()"
            )
        )
    try:
        with TestClient(app, base_url=TEST_BASE_URL, raise_server_exceptions=False) as raw:
            assert raw.post(VERIFY, json={"token": token}).status_code >= 500
    finally:
        with owner_engine.begin() as connection:
            connection.execute(text("DROP TRIGGER test_signup_fail ON signup_requests"))
            connection.execute(text("DROP FUNCTION test_signup_fail()"))
    assert _companies_named(owner_engine, form["shop_name"]) == 0
    assert enqueued == []
    row = _request(owner_engine, phone_e164=_e164(form["phone"]))
    assert row.status == "pending" and row.email_verified_at is None
    # Le jeton n'a pas été consommé : le même lien marche ensuite.
    assert client.post(VERIFY, json={"token": token}).json()["status"] == "ready"


# --- Limites ----------------------------------------------------------------------------


def test_limits_per_phone_and_email(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, enqueued: list[Any]
) -> None:
    _settings(monkeypatch, signup_phone_per_day=2, signup_email_per_day=2)
    phone = _phone()
    for _ in range(2):
        assert client.post(CREATE, json=_form(phone=phone)).status_code == 202
    third = client.post(CREATE, json=_form(phone=phone))
    assert third.status_code == 429 and third.json()["error"]["details"]["scope"] == "signup_phone"
    email = f"lim-{uuid4().hex[:6]}@example.com"
    for _ in range(2):
        client.post(CREATE, json=_form(email=email))
    assert client.post(CREATE, json=_form(email=email)).status_code == 429


def test_the_global_hourly_cap_refuses_visibly(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, enqueued: list[Any]
) -> None:
    _settings(monkeypatch, signup_global_per_hour=1)
    assert client.post(CREATE, json=_form()).status_code == 202
    over = client.post(CREATE, json=_form())
    assert over.status_code == 429 and "Retry-After" in over.headers


def test_the_automatic_cap_sends_requests_to_the_team_and_alerts(
    client: TestClient,
    owner_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    enqueued: list[tuple[str, dict[str, Any]]],
) -> None:
    _settings(monkeypatch, signup_auto_per_day=1)
    assert client.post(CREATE, json=_form()).json()["path"] == "email"
    over = _form()
    assert client.post(CREATE, json=over).json()["path"] == "team"
    assert _request(owner_engine, phone_e164=_e164(over["phone"])).path == "team"
    assert signup_service.AUTOMATIC_CAP_TASK in [name for name, _ in enqueued]


def test_limits_by_ip_use_a_keyed_hash(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, owner_engine: Engine, enqueued: list[Any]
) -> None:
    _settings(monkeypatch, signup_ip_per_hour=1)
    monkeypatch.setattr(signup_router, "client_ip", lambda request: "203.0.113.7")
    form = _form()
    assert client.post(CREATE, json=form).status_code == 202
    assert client.post(CREATE, json=_form()).status_code == 429
    stored = _request(owner_engine, phone_e164=_e164(form["phone"])).ip_hash
    assert stored != hashlib.sha256(b"203.0.113.7").hexdigest()
    assert stored != hashlib.sha256(b"ip:203.0.113.7").hexdigest()
    redis_client = cache.get_client()
    assert redis_client is not None
    keys = list(redis_client.scan_iter("coges:signup:*"))
    assert keys and all("203.0.113.7" not in key for key in keys)
    assert all(redis_client.ttl(key) > 0 for key in keys)


def test_without_redis_requests_are_refused(
    client: TestClient, owner_engine: Engine, signup_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits.cache, "get_client", lambda: None)
    form = _form()
    refused = client.post(CREATE, json=form)
    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "signup_unavailable"
    assert _request(owner_engine, phone_e164=_e164(form["phone"])) is None


# --- Tâches de fond ---------------------------------------------------------------------


def test_maintenance_switches_abandons_then_purges(
    client: TestClient,
    owner_engine: Engine,
    signup_on: None,
    enqueued: list[Any],
    admin_headers: dict[str, str],
) -> None:
    stale_email, stale_team, refused = _form(), _form(email=None), _form(email=None)
    for form in (stale_email, stale_team, refused):
        client.post(CREATE, json=form)
    ids = {
        key: _request(owner_engine, phone_e164=_e164(form["phone"])).id
        for key, form in (("email", stale_email), ("team", stale_team), ("refused", refused))
    }
    rejected = client.post(
        f"{ADMIN}/{ids['refused']}/reject",
        headers=admin_headers,
        json={"reason": "unreachable", "note": "Pas de réponse"},
    )
    assert rejected.status_code == 200 and rejected.json()["reject_reason"] == "unreachable"
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE signup_requests SET created_at = now() - interval '49 hours' WHERE id = :id"
            ),
            {"id": ids["email"]},
        )
        connection.execute(
            text(
                "UPDATE signup_requests SET path_changed_at = now() - interval '8 days' "
                "WHERE id = :id"
            ),
            {"id": ids["team"]},
        )
        connection.execute(
            text(
                "UPDATE signup_requests SET decided_at = now() - interval '31 days' WHERE id = :id"
            ),
            {"id": ids["refused"]},
        )

    first = signup_tasks.maintenance.run()
    assert first["switched_to_team"] >= 1 and first["abandoned"] >= 1 and first["purged"] >= 1
    rows = {
        row.id: row
        for row in _owner_rows(
            owner_engine,
            "SELECT * FROM signup_requests WHERE id = ANY(:ids)",
            ids=list(ids.values()),
        )
    }
    assert rows[ids["email"]].path == "team"
    assert rows[ids["team"]].status == "abandoned"
    purged = rows[ids["refused"]]
    assert purged.purged_at is not None
    assert (purged.full_name, purged.phone, purged.email, purged.password_hash) == (
        None,
        None,
        None,
        None,
    )
    assert purged.status == "rejected" and purged.reject_reason == "unreachable"
    # Idempotente : rejouée, elle ne retouche rien de ce qu'elle a déjà fait.
    again = signup_tasks.maintenance.run()
    assert (
        rows[ids["refused"]].purged_at
        == _owner_rows(
            owner_engine, "SELECT purged_at FROM signup_requests WHERE id = :id", id=ids["refused"]
        )[0].purged_at
    )
    assert again["purged"] == 0 or again["purged"] < first["purged"] + 1


# --- Droits de l'équipe -----------------------------------------------------------------


def test_team_routes_refuse_merchants_and_support_cannot_decide(
    client: TestClient,
    signup_on: None,
    enqueued: list[Any],
    alpha_token: str,
    owner_engine: Engine,
) -> None:
    form = _form(email=None)
    client.post(CREATE, json=form)
    row = _request(owner_engine, phone_e164=_e164(form["phone"]))
    for method, path in (
        ("get", ADMIN),
        ("get", f"{ADMIN}/{row.id}"),
        ("post", f"{ADMIN}/{row.id}/activate"),
    ):
        refused = getattr(client, method)(path, headers=auth_headers(alpha_token))
        assert refused.status_code == 401, (method, path)

    support = create_platform_account("support")
    headers = auth_headers(platform_login(client, support))
    assert client.get(ADMIN, headers=headers).status_code == 200
    assert client.get(f"{ADMIN}/stats", headers=headers).status_code == 200
    for path, body in (
        (f"{ADMIN}/{row.id}/activate", None),
        (f"{ADMIN}/{row.id}/reject", {"reason": "other"}),
    ):
        assert client.post(path, headers=headers, json=body).status_code == 403
    assert (
        client.put(f"{ADMIN}/{row.id}/note", headers=headers, json={"note": "x"}).status_code == 403
    )


def test_stats_count_by_path_and_outcome(
    client: TestClient, signup_on: None, enqueued: list[Any], admin_headers: dict[str, str]
) -> None:
    before = client.get(f"{ADMIN}/stats", headers=admin_headers).json()
    client.post(CREATE, json=_form())
    client.post(CREATE, json=_form(email=None))
    after = client.get(f"{ADMIN}/stats", headers=admin_headers).json()
    assert after["received_email"] == before["received_email"] + 1
    assert after["received_team"] == before["received_team"] + 1
    assert after["smtp_configured"] is True


def test_the_shop_code_avoids_reserved_words_and_taken_codes() -> None:
    assert signup_service.slug_candidates("Démo")[0] == "demo-2"
    assert signup_service.slug_candidates("Admin")[0] == "admin-2"
    assert signup_service.slug_candidates("Chez Fatou & Fils")[0] == "chez-fatou-fils"
    assert signup_service.slug_candidates("ÉÀ")[0] == "boutique-ea"
    assert all(len(candidate) <= 40 for candidate in signup_service.slug_candidates("x" * 90))


def test_onboarding_is_shared_with_the_command_line() -> None:
    import inspect

    from app import cli

    assert "signup_service.onboard_company" in inspect.getsource(cli.create_company)
