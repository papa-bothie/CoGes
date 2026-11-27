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

from datetime import date, datetime
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core import mailer, renewal
from app.core.config import get_settings
from app.core.display import dmy
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.companies import service as companies_service
from app.modules.notifications import service as notifications_service
from app.modules.notifications.schemas import NotificationType
from app.modules.platform import service as platform_service
from app.modules.rbac import service as rbac_service
from app.modules.users import service as users_service
from app.workers.beat import RENEWAL_NOTICE, SUBSCRIPTIONS_DAILY, SUPPORT_SESSIONS_CLOSE
from app.workers.celery_app import celery_app
from app.workers.jobs import tracked_job

#: Noms repris tels quels par `app.modules.platform.service`.
STATUS_CHANGED = "platform.company_status_changed"
LOGIN_FAILURES = "platform.login_failures"
SUPPORT_NOTICE = "platform.support_notice"
SEND_INVITATION = "platform.send_invitation"
SECURITY_NOTICE = "platform.security_notice"

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


# ------------------------------------------- double authentification (ADR 0105)

_SECURITY_SUBJECTS = {
    "new_device": "CoGes — connexion à l'administration depuis un nouvel appareil",
    "recovery_code_used": "CoGes — un code de secours a servi à vous connecter",
    "mfa_enabled": "CoGes — double authentification activée sur votre compte",
    "mfa_reset": "CoGes — votre double authentification a été réinitialisée",
}
_SECURITY_BODIES = {
    "new_device": (
        "Bonjour {name},\n\nVotre compte d'administration CoGes vient d'être utilisé depuis "
        "un appareil que nous ne connaissions pas ({device}), le {when}.\n\nSi c'est vous, "
        "rien à faire. Sinon, prévenez tout de suite un autre administrateur : il "
        "réinitialisera votre double authentification et fermera vos sessions."
    ),
    "recovery_code_used": (
        "Bonjour {name},\n\nUn de vos codes de secours vient de servir à vous connecter à "
        "l'administration CoGes ({device}), le {when}. Il ne servira plus.\n\nSi c'est vous, "
        "pensez à en générer de nouveaux (Ma sécurité). Sinon, prévenez tout de suite un "
        "autre administrateur."
    ),
    "mfa_enabled": (
        "Bonjour {name},\n\nLa double authentification de votre compte d'administration "
        "CoGes a été activée ({device}), le {when}.\n\nSi ce n'est pas vous, prévenez tout "
        "de suite un autre administrateur."
    ),
    "mfa_reset": (
        "Bonjour {name},\n\nLa double authentification de votre compte d'administration "
        "CoGes a été réinitialisée le {when} et vos sessions sont fermées. À votre prochaine "
        "connexion, vous l'enrôlerez à nouveau avec votre application.\n\nSi vous n'avez "
        "rien demandé, prévenez tout de suite un autre administrateur."
    ),
}


@celery_app.task(name=SECURITY_NOTICE, bind=True, max_retries=5, default_retry_delay=60)
def security_notice(self: Any, platform_user_id: str, kind: str, device: str | None) -> bool:
    """Prévient le compte (et l'équipe) d'un signal de sécurité. Sans SMTP, l'entrée reste
    visible dans « À traiter » et le journal."""
    if kind not in _SECURITY_SUBJECTS:
        return False
    recipient = platform_service.security_notice_recipient(UUID(platform_user_id))
    if recipient is None:
        return False
    team = get_settings().platform_alert_email
    when = datetime.now(ZoneInfo("Africa/Dakar")).strftime("%d/%m/%Y à %H h %M")
    to = [recipient.email] + ([team] if team and team != recipient.email else [])
    try:
        return mailer.send_email(
            to=to,
            subject=_SECURITY_SUBJECTS[kind],
            body=_SECURITY_BODIES[kind].format(
                name=recipient.display_name, device=device or "appareil inconnu", when=when
            )
            + "\n\nL'équipe CoGes",
        )
    except Exception as exc:
        raise self.retry(exc=exc) from exc


# ------------------------------------------- relances et suspension (ADR 0091, 0133)

TRIAL_SUMMARY = "platform.trial_summary"

_STAGE_WORDS = {
    "eve": "rappel de la veille",
    "due": "rappel du jour J",
    "last": "dernier rappel",
    "suspended": "mise en pause",
}
_EMAIL_HOW = (
    "Pour choisir ou renouveler votre offre, ouvrez CoGes, Réglages, « Mon abonnement », "
    "ou répondez simplement à ce message : nous vous accompagnons avec plaisir."
)
_EMAIL_PAUSED = (
    "Vos ventes, votre stock et vos clients restent exactement là où vous les avez "
    "laissés. Pour rouvrir votre boutique, répondez à ce message ou écrivez-nous sur "
    "WhatsApp : tout revient dès votre paiement."
)


def _email_body(name: str, text: str, stage: str) -> str:
    follow = _EMAIL_PAUSED if stage == "suspended" else _EMAIL_HOW
    return f"Bonjour,\n\n{name} — {text}\n\n{follow}\n\nÀ très bientôt,\nL'équipe CoGes"


@celery_app.task(name=SUBSCRIPTIONS_DAILY)
@tracked_job(SUBSCRIPTIONS_DAILY)
def subscriptions_daily(now: str | None = None) -> int:
    """Relance et suspend dans une transaction, puis enfile les messages (après COMMIT)."""
    moment = datetime.fromisoformat(now) if now else None
    notices = platform_service.run_subscription_day(moment)
    for notice in notices:
        renewal_notice.delay(
            company_id=str(notice.company_id),
            stage=notice.stage,
            kind=notice.kind,
            ends_at=notice.ends_at.isoformat(),
            plan_name=notice.plan_name,
            pause_on=notice.pause_on.isoformat(),
            today=notice.today.isoformat(),
        )
    if notices:
        trial_summary.delay(
            [
                {
                    "name": notice.company_name,
                    "stage": notice.stage,
                    "kind": notice.kind,
                    "ends": notice.ends_at.isoformat(),
                }
                for notice in notices
            ]
        )
    return len(notices)


@celery_app.task(name=RENEWAL_NOTICE, bind=True, max_retries=5, default_retry_delay=300)
@tracked_job(RENEWAL_NOTICE, ping_as=SUBSCRIPTIONS_DAILY)
def renewal_notice(
    self: Any,
    company_id: str,
    stage: str,
    kind: str,
    ends_at: str,
    plan_name: str,
    pause_on: str,
    today: str,
) -> bool:
    """Prévient une entreprise d'une étape (ADR 0133) : cloche et téléphone des gérants,
    e-mail à ceux qui en ont un. La pause n'a pas de cloche (la boutique ne se connecte
    plus) : l'e-mail seul.

    Rejouée, elle ne double rien : la cloche est dédoublonnée par étape et par échéance,
    et l'e-mail ne part qu'une fois la cloche posée pour la première fois.
    """
    stage_ = cast(renewal.Stage, stage)
    kind_ = cast(renewal.Kind, kind)
    days_left = max(1, (date.fromisoformat(pause_on) - date.fromisoformat(today)).days)
    title = renewal.title(stage_, kind_, days_left)
    text = renewal.message(stage_, kind_, plan_name, days_left)
    if stage_ != "suspended":
        ctx = TenantContext.bootstrap(UUID(company_id))
        with tenant_transaction(ctx) as session:
            first_time = (
                notifications_service.notify(
                    session,
                    ctx,
                    notification_type=NotificationType.TRIAL_ENDING,
                    title=title,
                    body=text,
                    entity_id=f"renewal:{stage_}:{ends_at}",
                    data={"stage": stage_, "kind": kind_, "ends_at": ends_at},
                    push=notifications_service.push_texts.renewal(stage_, kind_),
                    dedupe_hours=24 * 31,
                )
                > 0
            )
        if not first_time:
            return False
    try:
        name, emails = manager_emails(UUID(company_id))
        if emails:
            mailer.send_email(to=emails, subject=title, body=_email_body(name, text, stage_))
        return True
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(name=TRIAL_SUMMARY, bind=True, max_retries=3, default_retry_delay=300)
def trial_summary(self: Any, notices: list[dict[str, Any]]) -> bool:
    """Récapitulatif pour l'équipe (`COGES_PLATFORM_ALERT_EMAIL`) : les étapes du jour,
    puis les mises en pause."""
    team = get_settings().platform_alert_email
    if not team:
        return False
    ordered = sorted(notices, key=lambda item: item.get("stage") == "suspended")
    lines = [
        f"- {item['name']} : {_STAGE_WORDS.get(item.get('stage', ''), 'relance')} "
        f"({'essai' if item.get('kind') == 'trial' else 'abonnement'} jusqu'au "
        f"{dmy(datetime.fromisoformat(item['ends']).date())})"
        for item in ordered
    ]
    try:
        return mailer.send_email(
            to=[team],
            subject="CoGes — relances et mises en pause du jour",
            body="Relances traitées cette nuit (« À relancer » dans l'administration) :\n\n"
            + "\n".join(lines),
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
                push=notifications_service.push_texts.support_access(),
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


# ------------------------------------------------- invitations de l'équipe (ADR 0094)

_ROLE_TEXT = {
    "administrator": "administrateur (gestion de l'équipe, des entreprises et des abonnements)",
    "support": "support (consultation, sans modification de l'équipe ni des abonnements)",
}


@celery_app.task(name=SEND_INVITATION, bind=True, max_retries=5, default_retry_delay=60)
def send_invitation(self: Any, invitation_id: str, issue: int) -> bool:
    """Tire le jeton du lien ici, jamais dans Redis : la tâche ne porte que l'identifiant
    de l'invitation et son numéro d'émission. Un renvoi plus récent rend cet envoi muet."""
    if not mailer.is_configured():
        return False
    try:
        mail = platform_service.issue_invitation_token(UUID(invitation_id), issue)
        if mail is None:
            return False
        until = mail.expires_at.astimezone(ZoneInfo("Africa/Dakar"))
        return mailer.send_email(
            to=[mail.email],
            subject="Vous êtes invité dans l'équipe CoGes",
            body=(
                f"Bonjour {mail.display_name},\n\n{mail.inviter} vous invite à rejoindre "
                f"l'administration de CoGes, avec le profil {_ROLE_TEXT[mail.role]}.\n\n"
                f"Choisissez votre mot de passe en ouvrant ce lien :\n{mail.url}\n\n"
                f"Il est valable jusqu'au {dmy(until.date())} à {until:%H:%M} (heure de "
                "Dakar), une seule fois. Si vous n'attendiez pas cette invitation, ignorez "
                "ce message.\n\nL'équipe CoGes"
            ),
        )
    except Exception as exc:
        raise self.retry(exc=exc) from exc
