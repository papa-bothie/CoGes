"""E-mails et entretien de l'inscription libre-service (ADR 0118).

Tâches enfilées par `app.modules.signup.service` par leur nom, **après** le COMMIT :

* `signup.send_verification` tire lui-même le jeton (il ne passe jamais par Redis), en
  garde l'empreinte, puis écrit à l'adresse de la demande ;
* `signup.already_registered`, `signup.welcome` : l'adresse a déjà un compte, la
  boutique est prête ;
* `signup.notify_team`, `signup.automatic_cap_reached` : l'équipe est prévenue
  (`COGES_PLATFORM_ALERT_EMAIL`) d'une demande de son ressort ou du plafond atteint.

Et la tâche planifiée `signup.maintenance` (toutes les heures, `job_runs`) : bascule vers
l'équipe à 48 h, abandon à 7 jours, effacement des données personnelles à 30 jours.

Sans SMTP, rien ne part et rien n'échoue (`app/core/mailer.py`).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core import mailer
from app.core.config import get_settings
from app.core.deps import platform_transaction
from app.modules.signup import emails
from app.modules.signup import service as signup_service
from app.workers.beat import SIGNUP_MAINTENANCE
from app.workers.celery_app import celery_app
from app.workers.jobs import tracked_job


def _login_link(slug: str | None = None) -> str:
    base = f"{get_settings().merchant_url.rstrip('/')}/login"
    return f"{base}?boutique={slug}" if slug else base


def _send(to: str, email: emails.Email) -> bool:
    return mailer.send_email(to=[to], subject=email.subject, body=email.body, html=email.html)


@celery_app.task(
    name=signup_service.SEND_VERIFICATION_TASK, bind=True, max_retries=5, default_retry_delay=60
)
def send_verification(self: Any, request_id: str) -> bool:
    if not mailer.is_configured():
        return False
    issued = signup_service.issue_verification(UUID(request_id))
    if issued is None:
        return False
    token, address, shop_name = issued
    message = emails.verification(
        shop_name=shop_name,
        link=signup_service.verification_link(token),
        hours=get_settings().signup_token_ttl_hours,
    )
    try:
        return _send(address, message)
    except Exception as exc:
        # Le jeton déjà posé est remplacé au nouvel essai : l'ancien ne servira jamais.
        raise self.retry(exc=exc) from exc


@celery_app.task(
    name=signup_service.ALREADY_REGISTERED_TASK, bind=True, max_retries=3, default_retry_delay=60
)
def already_registered(self: Any, email: str) -> bool:
    try:
        return _send(email, emails.already_registered(login_link=_login_link()))
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(name=signup_service.WELCOME_TASK, bind=True, max_retries=5, default_retry_delay=60)
def welcome(self: Any, company_id: str, user_id: str) -> bool:
    address, slug = signup_service.manager_contact(UUID(company_id), UUID(user_id))
    if not address:
        return False
    try:
        return _send(address, emails.welcome(company_slug=slug, login_link=_login_link(slug)))
    except Exception as exc:
        raise self.retry(exc=exc) from exc


def _alert_team(subject: str, lines: list[str]) -> bool:
    team = get_settings().platform_alert_email
    if not team:
        return False
    link = f"{get_settings().admin_url.rstrip('/')}/demandes"
    return _send(team, emails.team_alert(subject=subject, lines=lines, link=link))


@celery_app.task(
    name=signup_service.NOTIFY_TEAM_TASK, bind=True, max_retries=3, default_retry_delay=60
)
def notify_team(self: Any, request_id: str) -> bool:
    # Ni nom ni numéro dans l'e-mail : l'équipe les lit dans l'administration.
    try:
        return _alert_team(
            "CoGes — une demande d'inscription attend l'équipe",
            ["Une nouvelle demande d'inscription attend d'être activée.", f"Demande {request_id}"],
        )
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(
    name=signup_service.AUTOMATIC_CAP_TASK, bind=True, max_retries=3, default_retry_delay=60
)
def automatic_cap_reached(self: Any) -> bool:
    try:
        return _alert_team(
            "CoGes — plafond d'activations automatiques atteint",
            [
                "Le plafond quotidien d'activations par lien e-mail est atteint.",
                "Les nouvelles demandes passent par l'équipe jusqu'à demain.",
            ],
        )
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(name=SIGNUP_MAINTENANCE)
@tracked_job(SIGNUP_MAINTENANCE)
def maintenance() -> dict[str, int]:
    """Idempotente : rejouée, elle ne retouche aucune demande déjà traitée."""
    with platform_transaction() as session:
        done = signup_service.maintenance(session)
    return {
        "switched_to_team": done.switched_to_team,
        "abandoned": done.abandoned,
        "purged": done.purged,
    }
