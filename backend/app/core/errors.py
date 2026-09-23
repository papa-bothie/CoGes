"""Erreurs métier et format de réponse unique.

Toute erreur sort au format `{"error": {"code", "message", "details"}}` :
code stable en anglais `snake_case`, message affiché en français.

Règle de sécurité : accéder à la ressource d'un autre tenant renvoie **404**,
avec le code `not_found`, strictement indiscernable d'une ressource inexistante.
Un 403 révélerait l'existence de la ressource.
"""

from __future__ import annotations

from typing import Any


class CogesError(Exception):
    """Erreur métier convertible en réponse HTTP."""

    code: str = "internal_error"
    status_code: int = 500
    default_message: str = "Une erreur interne est survenue."

    def __init__(self, message: str | None = None, *, details: dict[str, Any] | None = None):
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        """Corps de réponse normalisé."""
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class NotFoundError(CogesError):
    code = "not_found"
    status_code = 404
    default_message = "Ressource introuvable."


class CrossTenantAccessError(NotFoundError):
    """Accès à la donnée d'une autre entreprise.

    Hérite de `NotFoundError` : même code, même statut, aucune information révélée.
    """


class AuthenticationRequiredError(CogesError):
    code = "authentication_required"
    status_code = 401
    default_message = "Authentification requise."


class PermissionDeniedError(CogesError):
    code = "permission_denied"
    status_code = 403
    default_message = "Vous n'avez pas la permission d'effectuer cette action."


class ValidationFailedError(CogesError):
    code = "validation_failed"
    status_code = 422
    default_message = "Les données envoyées sont invalides."


class TenantContextError(CogesError):
    """Le contexte tenant est absent, incohérent ou posé hors transaction.

    C'est un défaut de programmation, jamais une erreur utilisateur : la requête
    échoue en 500 plutôt que de s'exécuter sans isolation.
    """

    code = "tenant_context_error"
    status_code = 500
    default_message = "Contexte d'entreprise invalide."


class TenantIsolationError(CogesError):
    """Tentative d'écrire une ligne rattachée à une autre entreprise."""

    code = "tenant_isolation_error"
    status_code = 500
    default_message = "Écriture refusée : la ligne appartient à une autre entreprise."
