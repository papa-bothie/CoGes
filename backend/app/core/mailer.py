"""Envoi d'e-mails par SMTP, bibliothèque standard seulement (ADR 0089).

Aucun service payant imposé : n'importe quel relais SMTP convient (celui de
l'hébergeur de la boîte de l'équipe, par exemple). Sans `COGES_SMTP_HOST`, rien ne
part : l'intention est journalisée **sans** destinataire ni contenu, et l'appelant
continue — un e-mail manqué ne doit jamais défaire une action déjà validée.

N'est appelé que depuis le worker, jamais dans une requête HTTP : un serveur SMTP lent
ne retient personne.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_FROM = "CoGes <no-reply@coges.invalid>"


def is_configured() -> bool:
    return bool(get_settings().smtp_host)


def send_email(*, to: list[str], subject: str, body: str) -> bool:
    """Envoie un message texte. `False` si l'envoi n'est pas configuré ou n'a personne à qui
    écrire ; une erreur SMTP remonte, pour que la tâche réessaie."""
    settings = get_settings()
    recipients = [address for address in to if address]
    if not settings.smtp_host:
        logger.info("E-mail non envoyé : COGES_SMTP_HOST absent", extra={"subject": subject})
        return False
    if not recipients:
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from or DEFAULT_FROM
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
    ) as client:
        if settings.smtp_starttls:
            client.starttls(context=ssl.create_default_context())
        if settings.smtp_username and settings.smtp_password:
            client.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        client.send_message(message)
    return True
