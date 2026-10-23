"""E-mails de l'administration de la plateforme (ADR 0089).

Deux tâches, enfilées par `app.modules.platform.service` par leur nom :

* le gérant d'une entreprise suspendue ou réactivée en est prévenu. Son adresse est lue
  ici, dans le contexte de son entreprise (`coges_app`), jamais transportée par Redis ;
* l'équipe est prévenue d'échecs de connexion répétés sur un compte de l'administration
  (`COGES_PLATFORM_ALERT_EMAIL`), puisqu'il n'y a pas de gérant à ce niveau.

Sans SMTP configuré, rien ne part et rien n'échoue (`app/core/mailer.py`).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core import mailer
from app.core.config import get_settings
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.companies import service as companies_service
from app.modules.rbac import service as rbac_service
from app.modules.users import service as users_service
from app.workers.celery_app import celery_app

#: Noms repris tels quels par `app.modules.platform.service`.
STATUS_CHANGED = "platform.company_status_changed"
LOGIN_FAILURES = "platform.login_failures"

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
