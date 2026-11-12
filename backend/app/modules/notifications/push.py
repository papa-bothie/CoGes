"""Ce qu'une notification dit sur l'écran verrouillé (ADR 0120). Fonctions pures.

Décision du propriétaire : **le détail utile, sans aucun montant**. Un téléphone posé
sur le comptoir montre ces textes à qui passe : un nom d'article, un numéro de vente,
un prénom, oui ; une somme d'argent ou un numéro de téléphone, jamais.

Chaque type d'alerte a son constructeur, appelé par le worker qui crée l'alerte ; le
texte est gardé dans `notifications.data["push"]` et relu après le COMMIT par l'envoi.
`safe_message` revérifie au dernier moment : un nom d'article qui contiendrait un prix
(« Sac 5 000 F ») ne sort pas, le texte générique le remplace.

Le chemin d'arrivée est **relatif à l'application** (`/sales/…`), vérifié ici et par
le service worker : une notification ne mène jamais hors de CoGes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

#: Une somme : des chiffres suivis d'une devise (« 5 000 F », « 12000 FCFA », « 3 XOF »).
_MONEY = re.compile(r"\d[\d\s\u00a0\u202f.,]*\s*(?:F|(?i:FCFA|CFA|XOF|francs?))(?![A-Za-zÀ-ÿ0-9])")
#: Un numéro de téléphone : huit chiffres ou plus, séparés ou non.
_PHONE = re.compile(r"(?:\+?\d[\s  .\-]?){8,}")
#: Chemin de l'application : une barre, puis ni barre ni barre oblique inverse, sans schéma.
_APP_PATH = re.compile(r"^/(?![/\\])[A-Za-z0-9/_\-?=&.%]*$")

#: Tâche du worker qui envoie, enfilée par `notify()` après le COMMIT.
PUSH_DELIVER = "notifications.push_deliver"

#: Types dont la personne qui a agi n'est pas notifiée sur son propre téléphone (choix
#: du propriétaire, ADR 0120) : elle sait ce qu'elle vient de faire. L'alerte reste dans
#: sa cloche. Le stock bas, lui, part toujours, même après sa propre vente.
SELF_SILENT_TYPES = frozenset({"sale_cancelled"})

#: Rafale : au-delà de 3 alertes en une minute pour une personne, une seule notification.
BURST_WINDOW_SECONDS = 60
BURST_THRESHOLD = 3

#: Texte de repli, quand un texte construit ne passe pas le contrôle.
FALLBACK_TITLE = "Nouvelle alerte dans CoGes"
FALLBACK_BODY = "Touchez pour la voir."
ALERTS_PATH = "/notifications"

#: Longueurs affichées sans coupure par la plupart des écrans verrouillés.
TITLE_MAX = 80
BODY_MAX = 140


@dataclass(frozen=True, slots=True)
class PushMessage:
    title: str
    body: str
    url: str

    def as_data(self) -> dict[str, str]:
        return {"title": self.title, "body": self.body, "url": self.url}


def shows_money_or_phone(text: str) -> bool:
    """Le texte montre-t-il une somme ou un numéro de téléphone ?"""
    return bool(_MONEY.search(text) or _PHONE.search(text))


def is_app_path(url: str) -> bool:
    """Chemin relatif de l'application : `/…`, jamais `//hôte` ni `https://`."""
    return bool(_APP_PATH.fullmatch(url))


def safe_message(title: str, body: str, url: str) -> PushMessage:
    """Le message tel qu'il partira : sans somme, sans numéro, chemin relatif sûr."""
    if shows_money_or_phone(title) or shows_money_or_phone(body):
        title, body = FALLBACK_TITLE, FALLBACK_BODY
    return PushMessage(
        title=title[:TITLE_MAX],
        body=body[:BODY_MAX],
        url=url if is_app_path(url) else ALERTS_PATH,
    )


def message_of(data: dict[str, Any]) -> PushMessage:
    """Relit le texte gardé dans `notifications.data["push"]`, et le revérifie."""
    stored = data.get("push")
    if not isinstance(stored, dict):
        return safe_message(FALLBACK_TITLE, FALLBACK_BODY, ALERTS_PATH)
    return safe_message(
        str(stored.get("title") or FALLBACK_TITLE),
        str(stored.get("body") or ""),
        str(stored.get("url") or ALERTS_PATH),
    )


def burst(count: int) -> PushMessage:
    """Une rafale regroupée (plus de 3 alertes en une minute) : « 4 nouvelles alertes »."""
    return PushMessage(
        title=f"{count} nouvelles alertes", body="Touchez pour les voir.", url=ALERTS_PATH
    )


def short_name(full_name: str | None) -> str | None:
    """« Moussa Diop » → « Moussa D. » : assez pour reconnaître, pas pour tout dire."""
    words = (full_name or "").split()
    if not words:
        return None
    if len(words) == 1:
        return words[0]
    return f"{words[0]} {words[-1][0].upper()}."


def first_name(full_name: str | None) -> str | None:
    words = (full_name or "").split()
    return words[0] if words else None


# ----------------------------------------------------------- un texte par type


def stock_low(label: str, quantity: str, product_id: UUID) -> PushMessage:
    """« Riz 25 kg : stock bas (3 sacs) »."""
    return PushMessage(
        title=f"{label} : stock bas ({quantity})",
        body="Pensez à commander.",
        url=f"/inventory/receive?product={product_id}",
    )


def stock_out(label: str, product_id: UUID) -> PushMessage:
    """« Riz 25 kg est épuisé »."""
    return PushMessage(
        title=f"{label} est épuisé",
        body="Vous ne pouvez plus en vendre.",
        url=f"/inventory/receive?product={product_id}",
    )


def debt_due(name: str | None, party_type: str, party_id: UUID | None) -> PushMessage:
    """« Moussa D. n'a pas payé à temps » ; un fournisseur : « À payer à … : date dépassée ».

    Les mots de l'alerte de la cloche (ADR 0074), pas « échéance » (lexique, ADR 0069).
    """
    who = short_name(name)
    if party_type == "supplier":
        title = f"À payer à {who} : date dépassée" if who else "Un fournisseur est à payer"
        url = f"/finance/pay?supplier={party_id}" if party_id else "/finance/debts?overdue=1"
        return PushMessage(title=title, body="La date de paiement est passée.", url=url)
    title = f"{who} n'a pas payé à temps" if who else "Un client n'a pas payé à temps"
    url = f"/finance/collect?customer={party_id}" if party_id else "/finance/debts?overdue=1"
    return PushMessage(title=title, body="Touchez pour encaisser.", url=url)


def sale_cancelled(
    number: str, actor: str | None, *, corrected: bool, sale_id: UUID
) -> PushMessage:
    """« Vente n° 42 annulée par Awa », ou « corrigée par Awa » (ADR 0119)."""
    verb = "corrigée" if corrected else "annulée"
    who = first_name(actor)
    title = f"Vente n° {number} {verb} par {who}" if who else f"Vente n° {number} {verb}"
    body = "Une nouvelle vente la remplace." if corrected else "Les articles sont revenus en stock."
    return PushMessage(title=title, body=body, url=f"/sales/{sale_id}")


def insight_critical(insight_type: str) -> PushMessage:
    """Un conseil grave : le détail (souvent chiffré) reste dans l'application."""
    return PushMessage(
        title="Un conseil important vous attend",
        body="Ouvrez CoGes pour le lire.",
        url=f"/insights?type={insight_type}",
    )


def login_failures(name: str) -> PushMessage:
    return PushMessage(
        title=f"Connexions échouées sur le compte de {first_name(name) or name}",
        body="Si ce n'est pas cette personne, changez son mot de passe.",
        url="/settings/people",
    )


#: « dans 3 jours », « demain », « aujourd'hui » (J-7, J-3, J-1, J+0).
def trial_ending(days: int) -> PushMessage:
    when = {0: "aujourd'hui", 1: "demain"}.get(days, f"dans {days} jours")
    return PushMessage(
        title=f"Fin de l'essai {when}",
        body="Contactez l'équipe CoGes pour choisir votre offre.",
        url=ALERTS_PATH,
    )


def support_access() -> PushMessage:
    return PushMessage(
        title="Accès support ouvert par l'équipe CoGes",
        body="Lecture seule. La raison est dans votre historique.",
        url="/settings/history",
    )
