"""Licence sur site (ADR 0125) : un abonnement `active` sans fin, posé par une commande.

La preuve centrale : une entreprise licenciée n'est jamais suspendue par la tâche de nuit,
même 400 jours plus tard ; sans licence, la même entreprise l'est au 31ᵉ jour (témoin).
Puis le plafond de comptes de chaque offre, la descente refusée, la réactivation d'une
entreprise suspendue sans aucun message, l'idempotence, les refus, l'isolation, et la
preuve que la commande n'écrit rien d'autre que l'abonnement, l'accès et le journal.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app import cli
from app.core import queue
from app.core.errors import NotFoundError, ValidationFailedError, sqlstate
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.platform import service as platform_service
from tests.conftest import DemoCompany, _create_demo_company
from tests.integration.billing_harness import set_subscription, subscription_row

pytestmark = pytest.mark.usefixtures("platform_bound_to_test_database")

LICENSE_REASON = "licence sur site"
CAPS = {"starter": 3, "business": 7, "premium": 10}


@pytest.fixture
def shop() -> DemoCompany:
    return _create_demo_company(f"licence-{uuid4().hex[:8]}")


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def _record(task_name: str, **kwargs: Any) -> bool:
        calls.append((task_name, kwargs))
        return True

    monkeypatch.setattr(queue, "enqueue", _record)
    return calls


def _access(platform_session_factory: sessionmaker[Any], company_id: UUID) -> str:
    with platform_session_factory.begin() as session:
        return str(
            session.execute(
                text("SELECT status::text FROM companies WHERE id = :id"), {"id": company_id}
            ).scalar_one()
        )


def _audits(platform_session_factory: sessionmaker[Any], company_id: UUID) -> list[Any]:
    with platform_session_factory.begin() as session:
        return list(
            session.execute(
                text(
                    "SELECT entity_table, action, actor_id, diff FROM platform_audit_logs "
                    "WHERE target_company_id = :id ORDER BY id"
                ),
                {"id": company_id},
            )
        )


def _night(company_id: UUID) -> list[int]:
    """La tâche de nuit, maintenant ; les paliers vus pour cette entreprise seulement."""
    return [
        n.days
        for n in platform_service.run_subscription_day(datetime.now(UTC))
        if n.company_id == company_id
    ]


def _days_later(
    platform_session_factory: sessionmaker[Any], company_id: UUID, days: int
) -> list[int]:
    """La nuit du jour `days` de cette entreprise : sa fin d'essai (30 jours après la
    création) est reculée de `days` jours, et la tâche tourne maintenant.

    Avancer `now` de la tâche suspendrait **toutes** les entreprises en essai de la base
    de test, dont celles que la suite partage ; les tests de l'essai font de même.
    """
    created = subscription_row(platform_session_factory, company_id).started_at
    ends = created + timedelta(days=30) - timedelta(days=days)
    set_subscription(platform_session_factory, company_id, trial_ends_at=ends)
    return _night(company_id)


def _activate(shop: DemoCompany, plan: str = "premium", note: str | None = None) -> Any:
    return platform_service.activate_license(slug=shop.slug, plan_code=plan, note=note)


def _add_user(session_factory: sessionmaker[Any], company_id: UUID) -> UUID:
    with tenant_transaction(
        TenantContext.bootstrap(company_id), session_factory=session_factory
    ) as session:
        return session.execute(
            text(
                "INSERT INTO users (company_id, email, password_hash, full_name, is_active) "
                "VALUES (:company_id, :email, 'x', 'Compte de test', true) RETURNING id"
            ),
            {"company_id": company_id, "email": f"{uuid4().hex[:10]}@test.example"},
        ).scalar_one()


def _deactivate(session_factory: sessionmaker[Any], company_id: UUID, user_id: UUID) -> None:
    with tenant_transaction(
        TenantContext.bootstrap(company_id), session_factory=session_factory
    ) as session:
        session.execute(
            text("UPDATE users SET is_active = false, deactivated_at = now() WHERE id = :id"),
            {"id": user_id},
        )


def _fill_to(session_factory: sessionmaker[Any], company_id: UUID, count: int) -> list[UUID]:
    """Ajoute des comptes actifs jusqu'à `count` (le gérant compte pour un)."""
    return [_add_user(session_factory, company_id) for _ in range(count - 1)]


# ------------------------------------------------------------------- la preuve centrale


@pytest.mark.parametrize("days", [31, 90, 400])
def test_a_licensed_company_is_never_suspended_by_the_night(
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
    enqueued: list[tuple[str, dict[str, Any]]],
    days: int,
) -> None:
    _activate(shop)
    for day in (days - 24, days - 1, days):
        # ni avertissement ni suspension
        assert _days_later(platform_session_factory, shop.company_id, day) == []
    row = subscription_row(platform_session_factory, shop.company_id)
    assert (row.status, row.current_period_end) == ("active", None)
    assert _access(platform_session_factory, shop.company_id) == "active"
    assert enqueued == []


def test_without_licence_the_same_company_is_suspended_on_day_31(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    """Contrôle témoin : sans `activate_license`, la tâche de nuit suspend."""
    assert _days_later(platform_session_factory, shop.company_id, 31) == [0]
    assert subscription_row(platform_session_factory, shop.company_id).status == "suspended"
    assert _access(platform_session_factory, shop.company_id) == "suspended"


# --------------------------------------------------------------- offres et plafonds


@pytest.mark.parametrize("plan", sorted(CAPS))
def test_each_plan_caps_the_active_accounts_in_the_database(
    session_factory: sessionmaker[Any], shop: DemoCompany, plan: str
) -> None:
    _activate(shop, plan)
    _fill_to(session_factory, shop.company_id, CAPS[plan])
    with pytest.raises(DBAPIError) as caught:
        _add_user(session_factory, shop.company_id)
    assert sqlstate(caught.value) == "CG007"


def test_starter_to_business_raises_the_cap(
    session_factory: sessionmaker[Any],
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    _activate(shop, "starter")
    _fill_to(session_factory, shop.company_id, CAPS["starter"])
    result = _activate(shop, "business")
    assert (result.plan_code, result.max_users, result.changed) == ("business", 7, True)
    _add_user(session_factory, shop.company_id)  # le 4ᵉ passe désormais
    assert subscription_row(platform_session_factory, shop.company_id).plan_code == "business"


def test_business_to_starter_is_refused_until_back_under_the_cap(
    session_factory: sessionmaker[Any],
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    _activate(shop, "business")
    extra = _fill_to(session_factory, shop.company_id, 5)
    with pytest.raises(platform_service.PlanDowngradeTooManyUsersError) as refused:
        _activate(shop, "starter")
    assert refused.value.details == {"active_users": 5, "max_users": 3, "to_deactivate": 2}
    assert subscription_row(platform_session_factory, shop.company_id).plan_code == "business"

    for user_id in extra[:2]:
        _deactivate(session_factory, shop.company_id, user_id)
    assert _activate(shop, "starter").plan_code == "starter"


# ------------------------------------------------------- réactivation, idempotence


def test_a_suspended_company_gets_its_access_back_silently(
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
    enqueued: list[tuple[str, dict[str, Any]]],
) -> None:
    assert _days_later(platform_session_factory, shop.company_id, 31) == [0]
    before = len(_audits(platform_session_factory, shop.company_id))

    result = _activate(shop, "business", note="Contrat du 17/11/2026")
    assert (result.access_before, result.access_after) == ("suspended", "active")
    assert (result.status_before, result.status_after) == ("suspended", "active")
    assert _access(platform_session_factory, shop.company_id) == "active"
    assert enqueued == []  # aucun message : pas de SMTP sur site

    new = _audits(platform_session_factory, shop.company_id)[before:]
    assert [(row.entity_table, row.action, row.actor_id) for row in new] == [
        ("subscriptions", "update", None),
        ("companies", "update", None),
    ]
    subscription_diff, access_diff = new[0].diff, new[1].diff
    assert subscription_diff["before"] == {
        "plan": "starter",
        "status": "suspended",
        "current_period_end": None,
        "license": False,
    }
    assert subscription_diff["after"] == {
        "plan": "business",
        "status": "active",
        "current_period_end": None,
        "license": True,
    }
    assert subscription_diff["reason"] == LICENSE_REASON
    assert subscription_diff["note"] == "Contrat du 17/11/2026"
    assert access_diff["reason"] == LICENSE_REASON


def test_a_paid_period_becomes_endless(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    ends = datetime.now(UTC) + timedelta(days=20)
    set_subscription(
        platform_session_factory, shop.company_id, status="active", current_period_end=ends
    )
    result = _activate(shop)
    assert result.changed is True
    assert subscription_row(platform_session_factory, shop.company_id).current_period_end is None


def test_the_same_plan_twice_changes_nothing_and_audits_once(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    first = _activate(shop, "starter")
    count = len(_audits(platform_session_factory, shop.company_id))
    updated = subscription_row(platform_session_factory, shop.company_id).updated_at

    again = _activate(shop, "starter")
    assert (first.changed, again.changed) == (True, False)
    assert (again.status_before, again.status_after) == ("active", "active")
    assert len(_audits(platform_session_factory, shop.company_id)) == count
    assert subscription_row(platform_session_factory, shop.company_id).updated_at == updated


def test_another_plan_after_the_licence_is_audited(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    _activate(shop, "starter")
    count = len(_audits(platform_session_factory, shop.company_id))
    _activate(shop, "premium", note="Passage à Premium")
    new = _audits(platform_session_factory, shop.company_id)[count:]
    assert [row.entity_table for row in new] == ["subscriptions"]  # l'accès reste actif
    assert new[0].diff["before"]["plan"] == "starter"
    assert new[0].diff["after"]["plan"] == "premium"


# ------------------------------------------------------------------------ refus


def test_an_unknown_company_is_refused() -> None:
    with pytest.raises(NotFoundError):
        platform_service.activate_license(slug="aucune-boutique-ici", plan_code="starter")


def test_a_slug_that_only_contains_the_name_is_not_a_match(shop: DemoCompany) -> None:
    """La recherche par identifiant est exacte : un préfixe ne désigne aucune entreprise."""
    with pytest.raises(NotFoundError):
        platform_service.activate_license(slug=shop.slug[:-2], plan_code="starter")


def test_an_unknown_plan_is_refused(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    with pytest.raises(ValidationFailedError):
        _activate(shop, "gold")
    assert subscription_row(platform_session_factory, shop.company_id).status == "trial"


def test_a_plan_that_is_not_for_sale_is_refused(
    owner_engine: Any, platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    from tests.integration.billing_harness import unlimited_plan

    with unlimited_plan(owner_engine) as code, pytest.raises(ValidationFailedError):
        _activate(shop, code)
    assert subscription_row(platform_session_factory, shop.company_id).status == "trial"


def test_a_note_too_long_is_refused(shop: DemoCompany) -> None:
    with pytest.raises(ValidationFailedError):
        _activate(shop, note="x" * 501)


# ---------------------------------------------------------------------- isolation


def test_licensing_a_leaves_b_on_trial_and_followed_by_the_night(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    other = _create_demo_company(f"licence-b-{uuid4().hex[:8]}")
    before_b = subscription_row(platform_session_factory, other.company_id)
    _activate(shop)
    after_b = subscription_row(platform_session_factory, other.company_id)
    assert after_b == before_b
    assert _access(platform_session_factory, other.company_id) == "trial"
    assert _audits(platform_session_factory, other.company_id) == []
    assert _days_later(platform_session_factory, other.company_id, 31) == [0]
    assert _access(platform_session_factory, shop.company_id) == "active"


def _tables(session: Session) -> list[str]:
    return list(
        session.execute(
            text(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relispartition "
                "ORDER BY c.relname"
            )
        ).scalars()
    )


def _fingerprints(session: Session, exclude: Callable[[str], str] | None = None) -> dict[str, str]:
    """Empreinte de chaque table que le rôle de la session lit en entier (sous RLS)."""
    found: dict[str, str] = {}
    for table in _tables(session):
        try:
            with session.begin_nested():
                rows = session.execute(
                    text(f"SELECT t::text FROM {table} t ORDER BY 1")  # noqa: S608 - catalogue
                ).scalars()
                found[table] = hashlib.sha256("\n".join(rows).encode()).hexdigest()
        except DBAPIError:
            continue  # colonnes ou table non accordées à ce rôle : lues par l'autre rôle
    return found


def test_the_command_writes_nothing_but_subscription_access_and_journal(
    session_factory: sessionmaker[Any],
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
) -> None:
    def snapshot() -> tuple[dict[str, str], dict[str, str], Any]:
        with tenant_transaction(
            TenantContext.bootstrap(shop.company_id), session_factory=session_factory
        ) as session:
            tenant = _fingerprints(session)
        with platform_session_factory.begin() as session:
            platform = _fingerprints(session)
            company = session.execute(
                text("SELECT id, name, slug, deleted_at FROM companies WHERE id = :id"),
                {"id": shop.company_id},
            ).one()
        return tenant, platform, company

    tenant_before, platform_before, company_before = snapshot()
    _activate(shop, "business", note="Contrat")
    tenant_after, platform_after, company_after = snapshot()

    allowed = {"subscriptions", "companies", "platform_audit_logs"}
    assert tenant_before.keys() == tenant_after.keys()
    changed = {t for t in tenant_before if tenant_before[t] != tenant_after[t]}
    changed |= {t for t in platform_before if platform_before[t] != platform_after[t]}
    assert changed <= allowed, changed - allowed
    assert "platform_audit_logs" in changed  # la preuve que l'empreinte voit un changement
    assert company_after == company_before  # de `companies`, seul le statut bouge


# ------------------------------------------------------------------- license-status


def test_the_status_reads_every_field_and_writes_nothing(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    trial = platform_service.license_status(slug=shop.slug)
    assert (trial.access, trial.subscription_status) == ("trial", "trial")
    assert trial.plan_code == "starter"
    assert (trial.max_users, trial.active_users) == (3, 1)
    assert trial.trial_ends_at is not None and trial.current_period_end is None
    assert (trial.last_license_at, trial.last_license_note) == (None, None)

    _activate(shop, "starter", note="Contrat du 17/11/2026, maintenance au 17/11/2027")
    count = len(_audits(platform_session_factory, shop.company_id))
    updated = subscription_row(platform_session_factory, shop.company_id).updated_at
    licensed = platform_service.license_status(slug=shop.slug)
    assert (licensed.access, licensed.subscription_status) == ("active", "active")
    assert (licensed.plan_code, licensed.max_users) == ("starter", 3)
    assert licensed.current_period_end is None
    assert licensed.last_license_at is not None
    assert licensed.last_license_note == "Contrat du 17/11/2026, maintenance au 17/11/2027"
    assert len(_audits(platform_session_factory, shop.company_id)) == count
    assert subscription_row(platform_session_factory, shop.company_id).updated_at == updated

    _activate(shop, "starter")  # rien à faire : la dernière note reste
    assert platform_service.license_status(slug=shop.slug).last_license_note == (
        "Contrat du 17/11/2026, maintenance au 17/11/2027"
    )


def test_the_status_of_a_suspended_company(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    _days_later(platform_session_factory, shop.company_id, 31)
    status = platform_service.license_status(slug=shop.slug)
    assert (status.access, status.subscription_status) == ("suspended", "suspended")


def test_the_status_of_an_unknown_company_is_refused() -> None:
    with pytest.raises(NotFoundError):
        platform_service.license_status(slug="aucune-boutique-ici")


# --------------------------------------------------------------------- la commande


def test_the_command_says_what_it_did_in_french(
    shop: DemoCompany, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        ["activate-license", "--slug", shop.slug, "--plan", "business", "--note", "Contrat"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert f"Entreprise       : {shop.slug.replace('-', ' ').title()} ({shop.slug})" in out
    assert "Offre            : Business (business)" in out
    assert "Comptes          : 1 actif(s) sur 7 au plus" in out
    assert "Abonnement       : essai → actif, sans fin" in out
    assert "Accès            : essai → actif" in out
    assert "Licence activée." in out

    assert cli.main(["activate-license", "--slug", shop.slug, "--plan", "business"]) == 0
    assert "Licence déjà active, offre business : rien à faire." in capsys.readouterr().out


def test_the_status_command_prints_active_without_end(
    shop: DemoCompany, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["activate-license", "--slug", shop.slug, "--plan", "starter", "--note", "Contrat A"])
    capsys.readouterr()
    assert cli.main(["license-status", "--slug", shop.slug]) == 0
    out = capsys.readouterr().out
    assert "Accès            : actif" in out
    assert "Offre            : Pro (starter), 3 comptes au plus" in out
    assert "Comptes actifs   : 1" in out
    assert "Fin de période   : sans fin" in out
    assert "Dernière licence :" in out and "Contrat A" in out


@pytest.mark.parametrize(
    ("argv", "code", "message"),
    [
        (["--slug", "aucune-boutique-ici", "--plan", "starter"], 3, "Entreprise introuvable"),
        (["--plan", "gold"], 4, "Offre inconnue ou non proposée : gold"),
    ],
)
def test_the_command_refuses_with_a_clear_message_and_a_failing_code(
    shop: DemoCompany,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    code: int,
    message: str,
) -> None:
    if "--slug" not in argv:
        argv = ["--slug", shop.slug, *argv]
    assert cli.main(["activate-license", *argv]) == code
    assert message in capsys.readouterr().err


def test_the_command_refuses_a_downgrade_with_the_count(
    session_factory: sessionmaker[Any],
    platform_session_factory: sessionmaker[Any],
    shop: DemoCompany,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_subscription(platform_session_factory, shop.company_id, plan="business")
    _fill_to(session_factory, shop.company_id, 5)
    assert cli.main(["activate-license", "--slug", shop.slug, "--plan", "starter"]) == 5
    assert "Désactivez-en 2" in capsys.readouterr().err


def test_the_status_command_refuses_an_unknown_company(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["license-status", "--slug", "aucune-boutique-ici"]) == 3
    assert "Entreprise introuvable" in capsys.readouterr().err


def test_a_licence_is_marked_and_premium_is_accepted_on_quote(
    platform_session_factory: sessionmaker[Any], shop: DemoCompany
) -> None:
    """Premium n'est plus en vente libre (ADR 0132) mais se pose sur site, sur devis ; la
    licence se marque `is_license`, que lit l'écran « Mon abonnement »."""
    result = _activate(shop, "premium", note="Devis du 26/11/2026")
    assert (result.plan_code, result.max_users) == ("premium", 10)
    row = subscription_row(platform_session_factory, shop.company_id)
    assert (row.is_license, row.status, row.current_period_end) == (True, "active", None)
