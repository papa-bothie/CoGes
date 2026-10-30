"""Ce que peut chaque profil de l'équipe, déduit du code (ADR 0094).

Le profil exigé par une route est celui de ses dépendances : `require_platform_role(...)`
le porte (`platform_roles`), et `get_platform_admin_session` seule ouvre la route aux deux
profils. Rien n'est recopié à la main, sauf la **phrase** qui décrit chaque route ; le
test-registre fait échouer la CI quand une route `/platform` à profil n'en a pas, ou
qu'une phrase ne correspond plus à aucune route.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from fastapi.routing import APIRoute

from app.core.deps import get_platform_admin_session

PROFILES = ("administrator", "support")
PROFILE_TEXT: dict[str, tuple[str, str]] = {
    "administrator": (
        "Administrateur",
        "Gère l'équipe, les entreprises et leurs abonnements, ouvre un accès support et lit "
        "le journal.",
    ),
    "support": (
        "Support",
        "Consulte les entreprises, les comptes, les statistiques et le système, et ouvre un "
        "accès support en lecture seule. Ne modifie ni l'équipe ni les abonnements.",
    ),
}

_PLATFORM = "/api/v1/platform"

#: Une phrase par route à profil, en français, du point de vue de qui agit.
LABELS: dict[str, str] = {
    f"GET {_PLATFORM}/auth/me": "Voir son propre compte",
    f"POST {_PLATFORM}/auth/mfa/recovery-codes": "Régénérer ses codes de secours",
    f"GET {_PLATFORM}/companies": "Chercher une entreprise",
    f"GET {_PLATFORM}/companies/{{company_id}}": "Voir la fiche d'une entreprise",
    f"PATCH {_PLATFORM}/companies/{{company_id}}/status": "Suspendre ou réactiver une entreprise",
    f"GET {_PLATFORM}/plans": "Voir les offres",
    f"GET {_PLATFORM}/companies/{{company_id}}/subscription": "Voir l'abonnement d'une entreprise",
    f"PATCH {_PLATFORM}/companies/{{company_id}}/subscription": "Changer l'offre d'une entreprise",
    f"POST {_PLATFORM}/companies/{{company_id}}/payments": "Enregistrer un paiement",
    f"GET {_PLATFORM}/companies/{{company_id}}/support-sessions": "Voir les accès support",
    f"POST {_PLATFORM}/companies/{{company_id}}/support-sessions": "Ouvrir un accès support",
    f"POST {_PLATFORM}/support-sessions/{{session_id}}/token": "Reprendre son accès support",
    f"DELETE {_PLATFORM}/support-sessions/{{session_id}}": "Fermer un accès support",
    f"GET {_PLATFORM}/stats/overview": "Voir les statistiques",
    f"GET {_PLATFORM}/stats/revenue": "Voir le revenu déclaré",
    f"GET {_PLATFORM}/stats/signups": "Voir les nouvelles entreprises",
    f"GET {_PLATFORM}/system/workers": "Voir l'état du système",
    f"GET {_PLATFORM}/system/job-runs": "Voir l'historique des tâches",
    f"GET {_PLATFORM}/system/outbox": "Voir les événements en échec",
    f"GET {_PLATFORM}/team": "Voir l'équipe",
    f"GET {_PLATFORM}/team/summary": "Voir le bilan de l'équipe",
    f"POST {_PLATFORM}/team/invitations": "Inviter un collègue",
    f"POST {_PLATFORM}/team/invitations/{{invitation_id}}/resend": "Renvoyer une invitation",
    f"DELETE {_PLATFORM}/team/invitations/{{invitation_id}}": "Annuler une invitation",
    f"PATCH {_PLATFORM}/team/{{user_id}}": "Changer le profil d'un collègue ou le suspendre",
    f"POST {_PLATFORM}/team/{{user_id}}/mfa-reset": (
        "Réinitialiser la double authentification d'un collègue"
    ),
    f"GET {_PLATFORM}/users": "Consulter les comptes des commerçants",
    f"GET {_PLATFORM}/audit": "Lire le journal des modifications",
    f"GET {_PLATFORM}/roles": "Voir ce que peut chaque profil",
    f"GET {_PLATFORM}/attention": "Voir ce qui demande une action",
}


def walk(routes: Iterable[Any], prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    """Routes avec leur chemin complet, routeurs inclus compris."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from walk(nested.routes, prefix + route.include_context.prefix)


def _calls(dependant: Any) -> Iterator[Any]:
    for dependency in dependant.dependencies:
        yield dependency.call
        yield from _calls(dependency)


def route_profiles(route: APIRoute) -> tuple[str, ...] | None:
    """Profils admis par la route ; `None` : la route n'exige aucun compte de l'équipe."""
    allowed: tuple[str, ...] | None = None
    for call in _calls(route.dependant):
        roles = getattr(call, "platform_roles", None)
        if roles is not None:
            allowed = tuple(role for role in (allowed or PROFILES) if role in roles)
        elif call is get_platform_admin_session and allowed is None:
            allowed = PROFILES
    return allowed


def _profiled(routes: Iterable[Any]) -> Iterator[tuple[str, tuple[str, ...]]]:
    for path, route in walk(routes):
        if not path.startswith(_PLATFORM):
            continue
        profiles = route_profiles(route)
        if profiles is None:
            continue
        for method in sorted(route.methods or ()):
            yield f"{method} {path}", profiles


def capabilities(routes: Iterable[Any]) -> dict[str, list[tuple[str, str]]]:
    """Pour chaque profil, ses capacités `(clé, phrase)`, dans l'ordre des phrases."""
    allowed = dict(_profiled(routes))
    order = list(LABELS)
    return {
        profile: [
            (key, LABELS[key])
            for key in sorted(allowed, key=lambda k: order.index(k) if k in LABELS else 999)
            if profile in allowed[key] and key in LABELS
        ]
        for profile in PROFILES
    }


def registry_gaps(routes: Iterable[Any]) -> tuple[list[str], list[str]]:
    """Routes à profil sans phrase, et phrases sans route."""
    keys = {key for key, _ in _profiled(routes)}
    return sorted(keys - set(LABELS)), sorted(set(LABELS) - keys)
