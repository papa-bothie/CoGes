"""E-mails de l'inscription (ADR 0118), en français simple, texte et HTML léger.

Aucune donnée inutile, **jamais** le mot de passe. Le HTML n'a ni image distante ni
script : un titre, deux ou trois paragraphes et un bouton qui est un lien.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from app.core.config import get_settings


@dataclass(frozen=True, slots=True)
class Email:
    subject: str
    body: str
    html: str


def _whatsapp() -> tuple[str, str]:
    digits = get_settings().support_whatsapp
    return f"+{digits}", f"https://wa.me/{digits}"


def _html(title: str, paragraphs: list[str], button: tuple[str, str] | None = None) -> str:
    parts = [
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:1.5;'
        'color:#1e2320;max-width:520px;margin:0 auto;padding:24px">',
        f'<h1 style="font-size:22px;margin:0 0 16px">{escape(title)}</h1>',
    ]
    parts += [f'<p style="margin:0 0 14px">{paragraph}</p>' for paragraph in paragraphs]
    if button is not None:
        label, href = button
        parts.append(
            f'<p style="margin:20px 0"><a href="{escape(href, quote=True)}" '
            'style="display:inline-block;background:#1f6b46;color:#ffffff;'
            'text-decoration:none;font-weight:bold;padding:12px 20px;border-radius:10px">'
            f"{escape(label)}</a></p>"
        )
    parts.append('<p style="margin:24px 0 0;color:#5b625e">L\'équipe CoGes</p></div>')
    return "".join(parts)


def verification(*, shop_name: str, link: str, hours: int) -> Email:
    title = "Ouvrez votre boutique CoGes"
    body = (
        f"Bonjour,\n\nPour ouvrir « {shop_name} » sur CoGes, cliquez sur ce lien :\n\n"
        f"{link}\n\nLe lien marche pendant {hours} heures, une seule fois.\n\n"
        "Si ce n'est pas vous, ignorez ce message : rien ne sera créé.\n\nL'équipe CoGes"
    )
    html = _html(
        title,
        [
            f"Bonjour,<br>Pour ouvrir « {escape(shop_name)} » sur CoGes, cliquez sur le bouton.",
            f"Le lien marche pendant {hours} heures, une seule fois.",
            "Si ce n'est pas vous, ignorez ce message : rien ne sera créé.",
        ],
        ("Ouvrir ma boutique", link),
    )
    return Email(subject=title, body=body, html=html)


def already_registered(*, login_link: str) -> Email:
    """L'adresse a déjà un compte : on le dit et on propose la connexion, sans seconde
    boutique. Le message ne nomme aucune boutique."""
    phone, wa = _whatsapp()
    subject = "Vous avez déjà un compte CoGes"
    body = (
        "Bonjour,\n\nQuelqu'un (sans doute vous) a demandé à ouvrir une boutique CoGes avec "
        "cette adresse. Elle a déjà un compte : connectez-vous plutôt ici :\n\n"
        f"{login_link}\n\nCode de boutique oublié ? Écrivez-nous sur WhatsApp ({phone}).\n\n"
        "Si ce n'est pas vous, ignorez ce message.\n\nL'équipe CoGes"
    )
    html = _html(
        subject,
        [
            "Bonjour,<br>Quelqu'un (sans doute vous) a demandé à ouvrir une boutique CoGes "
            "avec cette adresse. Elle a déjà un compte : connectez-vous plutôt.",
            f'Code de boutique oublié ? <a href="{wa}">Écrivez-nous sur WhatsApp</a> '
            f"({escape(phone)}).",
            "Si ce n'est pas vous, ignorez ce message.",
        ],
        ("Me connecter", login_link),
    )
    return Email(subject=subject, body=body, html=html)


def welcome(*, company_slug: str, login_link: str) -> Email:
    phone, wa = _whatsapp()
    subject = "Votre boutique CoGes est prête"
    body = (
        "Bonjour,\n\nVotre boutique est ouverte, avec 30 jours d'essai gratuit.\n\n"
        f"Code de la boutique : {company_slug}\n"
        f"Connexion : {login_link}\n\n"
        "Connectez-vous avec votre e-mail ou votre numéro, et votre mot de passe.\n\n"
        f"Une question ? Écrivez-nous sur WhatsApp : {phone}\n\nL'équipe CoGes"
    )
    html = _html(
        subject,
        [
            "Bonjour,<br>Votre boutique est ouverte, avec 30 jours d'essai gratuit.",
            f"Code de la boutique : <strong>{escape(company_slug)}</strong>",
            "Connectez-vous avec votre e-mail ou votre numéro, et votre mot de passe.",
            f'Une question ? <a href="{wa}">Écrivez-nous sur WhatsApp</a> ({escape(phone)}).',
        ],
        ("Me connecter", login_link),
    )
    return Email(subject=subject, body=body, html=html)


def team_alert(*, subject: str, lines: list[str], link: str) -> Email:
    body = "\n".join([*lines, "", link])
    html = _html(subject, [escape(line) for line in lines], ("Ouvrir les demandes", link))
    return Email(subject=subject, body=body, html=html)
