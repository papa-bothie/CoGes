"""E-mails de l'administration de la plateforme (ADR 0089) et fin des essais (ADR 0091).

Deux tâches, enfilées par `app.modules.platform.service` par leur nom :

* le gérant d'une entreprise suspendue ou réactivée en est prévenu. Son adresse est lue
  ici, dans le contexte de son entreprise (`coges_app`), jamais transportée par Redis ;
* l'équipe est prévenue d'échecs de connexion répétés sur un compte de l'administration
  (`COGES_PLATFORM_ALERT_EMAIL`), puisqu'il n'y a pas de gérant à ce niveau.

Et la tâche de nuit des abonnements (`beat.py`, 06 h 30) : elle avertit à J-7, J-3 et J-1
puis suspend à l'échéance, sous `coges_app_platform`, et enfile après COMMIT une
sous-tâche par entreprise (e-mail chaleureux au gérant, notification dans la cloche).

Sans SMTP configuré, rien ne part et rien n'échoue (`app/core/mailer.py`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core import mailer
from app.core.config import get_settings
from app.core.display import dmy
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.companies import service as companies_service
from app.modules.notifications import service as notifications_service
from app.modules.notifications.schemas import NotificationType
from app.modules.platform import service as platform_service
from app.modules.rbac import service as rbac_service
from app.modules.users import service as users_service
from app.workers.beat import SUBSCRIPTIONS_DAILY, SUPPORT_SESSIONS_CLOSE, TRIAL_NOTICE
from app.workers.celery_app import celery_app
from app.workers.jobs import tracked_job

#: Noms repris tels quels par `app.modules.platform.service`.
STATUS_CHANGED = "platform.company_status_changed"
LOGIN_FAILURES = "platform.login_failures"
SUPPORT_NOTICE = "platform.support_notice"

MANAGER_ROLE = "gerant"

_SUBJECTS = {
    "suspended": "Votre accès à CoGes est suspendu",
    "active": "Votre accès à CoGes est rétabli",
}
_BODIES = {
    "suspended": (
        "Bonjour,\n\nL'accès de {name} à CoGes vient d'être suspendu par l'équipe CoGes. "
        "Vos données sont conservées, mais personne de votre entreprise ne peut se "
        "connecter pour l'instant.\n\nRépondez à ce message ou contactez l'équipe CoGes "
        "pour le rétablir.\n\nL'équipe CoGes"
    ),
    "active": (
        "Bonjour,\n\nL'accès de {name} à CoGes est rétabli : vous et votre équipe pouvez "
        "vous connecter à nouveau.\n\nL'équipe CoGes"
    ),
}


def manager_emails(company_id: UUID) -> tuple[str, list[str]]:
    """Nom de l'entreprise et adresses de ses gérants actifs."""
    ctx = TenantContext.bootstrap(company_id)
    with tenant_transaction(ctx) as session:
        name = companies_service.get_current_company(session, ctx).name
        role_id = rbac_service.system_role_id(session, ctx, MANAGER_ROLE)
        holders = rbac_service.holders_of_role(session, ctx, role_id) if role_id else []
        emails = [
            users_service.get_user(session, ctx, user_id).email
            for user_id in users_service.active_among(session, ctx, holders)
        ]
    return name, [email for email in emails if email]


@celery_app.task(name=STATUS_CHANGED, bind=True, max_retries=5, default_retry_delay=60)
def company_status_changed(self: Any, company_id: str, status: str) -> bool:
    if status not in _SUBJECTS:
        return False
    try:
        name, emails = manager_emails(UUID(company_id))
        return mailer.send_email(
            to=emails, subject=_SUBJECTS[status], body=_BODIES[status].format(name=name)
        )
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(name=LOGIN_FAILURES, bind=True, max_retries=3, default_retry_delay=60)
def login_failures(self: Any, platform_user_id: str, failures: int) -> bool:
    team = get_settings().platform_alert_email
    if not team:
        return False
    try:
        return mailer.send_email(
            to=[team],
            subject="CoGes — échecs de connexion répétés à l'administration",
            body=(
                f"{failures} échecs de connexion successifs sur le compte d'administration "
                f"{platform_user_id}. La connexion de ce compte est freinée ; si ce n'est "
                "pas l'un de vous, changez son mot de passe ou désactivez-le."
            ),
        )
    except Exception as exc:
        raise self.retry(exc=exc) from exc


# ----------------------------------------------------------- fin des essais (ADR 0091)

TRIAL_SUMMARY = "platform.trial_summary"

_WHEN = {7: "dans 7 jours", 3: "dans 3 jours", 1: "demain"}

_WARNING_BODY = (
    "Bonjour,\n\n"
    "Merci de faire confiance à CoGes pour {name} ! Votre essai gratuit se termine "
    "{when}, le {date}.\n\n"
    "Pour continuer sans la moindre interruption, choisissez simplement l'offre qui vous "
    "convient : répondez à ce message ou appelez-nous, nous vous accompagnons avec "
    "plaisir. Vos ventes, votre stock et vos clients restent exactement là où vous les "
    "avez laissés.\n\n"
    "À très bientôt,\nL'équipe CoGes"
)
_ENDED_BODY = (
    "Bonjour,\n\n"
    "Votre essai gratuit de CoGes pour {name} s'est terminé le {date}. Merci de l'avoir "
    "essayé !\n\n"
    "Toutes vos données sont bien gardées. Pour retrouver l'accès, il suffit de choisir "
    "votre offre : répondez à ce message ou appelez-nous, et nous rouvrons votre accès "
    "dès votre premier paiement.\n\n"
    "À très bientôt,\nL'équipe CoGes"
)


@celery_app.task(name=SUBSCRIPTIONS_DAILY)
@tracked_job(SUBSCRIPTIONS_DAILY)
def subscriptions_daily(now: str | None = None) -> int:
    """Avertit et suspend dans une transaction, puis enfile les messages (après COMMIT)."""
    moment = datetime.fromisoformat(now) if now else None
    notices = platform_service.run_subscription_day(moment)
    for notice in notices:
        trial_notice.delay(str(notice.company_id), notice.days, notice.trial_ends_at.isoformat())
    if notices:
        trial_summary.delay(
            [
                {
                    "name": notice.company_name,
                    "days": notice.days,
                    "ends": notice.trial_ends_at.isoformat(),
                }
                for notice in notices
            ]
        )
    return len(notices)


@celery_app.task(name=TRIAL_NOTICE, bind=True, max_retries=5, default_retry_delay=300)
@tracked_job(TRIAL_NOTICE, ping_as=SUBSCRIPTIONS_DAILY)
def trial_notice(self: Any, company_id: str, days: int, trial_ends_at: str) -> bool:
    """Prévient une entreprise : avertissement (7, 3, 1) ou fin d'essai (0).

    La cloche n'est posée que pour un avertissement (une entreprise suspendue ne se
    connecte plus). Rejouée, elle ne double rien : la notification est dédoublonnée par
    palier, et l'e-mail ne part qu'une fois la cloche posée pour la première fois.
    """
    ctx = TenantContext.bootstrap(UUID(company_id))
    ends = datetime.fromisoformat(trial_ends_at)
    first_time = True
    if days:
        with tenant_transaction(ctx) as session:
            first_time = (
                notifications_service.notify(
                    session,
                    ctx,
                    notification_type=NotificationType.TRIAL_ENDING,
                    title=f"Votre essai se termine {_WHEN[days]}",
                    body=(
                        f"Votre essai gratuit s'arrête le {dmy(ends.date())}. Pour continuer "
                        "sans interruption, contactez l'équipe CoGes : elle vous aide à "
                        "choisir votre offre."
                    ),
                    entity_id=f"trial:{days}",
                    data={"days": days, "trial_ends_at": trial_ends_at},
                    dedupe_hours=24 * 31,
                )
                > 0
            )
    if not first_time:
        return False
    try:
        name, emails = manager_emails(UUID(company_id))
        if days:
            subject = f"Votre essai de CoGes se termine {_WHEN[days]}"
            body = _WARNING_BODY.format(name=name, when=_WHEN[days], date=dmy(ends.date()))
        else:
            subject = "Votre essai de CoGes est terminé"
            body = _ENDED_BODY.format(name=name, date=dmy(ends.date()))
        return mailer.send_email(to=emails, subject=subject, body=body)
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(name=TRIAL_SUMMARY, bind=True, max_retries=3, default_retry_delay=300)
def trial_summary(self: Any, notices: list[dict[str, Any]]) -> bool:
    """Récapitulatif pour l'équipe (`COGES_PLATFORM_ALERT_EMAIL`) : qui finit, qui est coupé."""
    team = get_settings().platform_alert_email
    if not team:
        return False
    lines = [
        f"- {item['name']} : "
        + (
            f"essai terminé le {dmy(datetime.fromisoformat(item['ends']).date())}, accès suspendu"
            if item["days"] == 0
            else f"essai qui se termine {_WHEN[item['days']]}"
        )
        for item in notices
    ]
    try:
        return mailer.send_email(
            to=[team],
            subject="CoGes — fins d'essai du jour",
            body="Fins d'essai traitées cette nuit :\n\n" + "\n".join(lines),
        )
    except Exception as exc:
        raise self.retry(exc=exc) from exc


# ------------------------------------------------- accès support encadré (ADR 0092)

_SUPPORT_BODY = (
    "Bonjour,\n\n"
    "L'équipe CoGes vient d'ouvrir un accès à {name}, en lecture seule, jusqu'au {until}.\n\n"
    "Pourquoi : {justification}\n\n"
    "Pendant cet accès, l'équipe peut consulter vos ventes, votre stock et votre argent, "
    "sans rien modifier. Un bandeau le signale à tous les utilisateurs de votre "
    "entreprise, et votre journal d'activité garde la trace de l'ouverture et de la "
    "fermeture.\n\n"
    "Si vous n'avez rien demandé, répondez à ce message : nous vous expliquerons.\n\n"
    "L'équipe CoGes"
)


@celery_app.task(name=SUPPORT_NOTICE, bind=True, max_retries=5, default_retry_delay=60)
def support_notice(self: Any, company_id: str, session_id: str, expires_at: str) -> bool:
    """Prévient l'entreprise d'un accès support (bris de glace) : cloche des personnes qui
    gèrent les comptes, et e-mail immédiat au(x) gérant(s). Rejouée, elle ne double rien :
    l'e-mail ne part qu'une fois la cloche posée pour la première fois."""
    ctx = TenantContext.bootstrap(UUID(company_id))
    with tenant_transaction(ctx) as session:
        tz = ZoneInfo(companies_service.get_timezone(session, ctx))
        until = datetime.fromisoformat(expires_at).astimezone(tz)
        first_time = (
            notifications_service.notify(
                session,
                ctx,
                notification_type=NotificationType.SUPPORT_ACCESS,
                title="L'équipe CoGes consulte votre boutique",
                body=(
                    f"Accès en lecture seule jusqu'à {until:%H:%M}. "
                    "Le motif est dans votre journal d'activité."
                ),
                entity_id=f"support:{session_id}",
                data={"session_id": session_id, "expires_at": expires_at},
                dedupe_hours=24,
            )
            > 0
        )
    if not first_time:
        return False
    try:
        justification = platform_service.support_justification(UUID(session_id)) or "—"
        name, emails = manager_emails(UUID(company_id))
        return mailer.send_email(
            to=emails,
            subject="L'équipe CoGes consulte votre boutique",
            body=_SUPPORT_BODY.format(
                name=name,
                until=f"{dmy(until.date())} à {until:%H:%M}",
                justification=justification,
            ),
        )
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(name=SUPPORT_SESSIONS_CLOSE)
@tracked_job(SUPPORT_SESSIONS_CLOSE)
def support_sessions_close(now: str | None = None) -> int:
    """Ferme à leur échéance les accès support restés ouverts (sous `coges_app_platform`)."""
    moment = datetime.fromisoformat(now) if now else None
    return platform_service.close_expired_support_sessions(moment)
