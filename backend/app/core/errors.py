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
        # En-têtes HTTP à joindre à la réponse (`Retry-After` d'un 429, par exemple).
        self.headers: dict[str, str] = {}
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        """Corps de réponse normalisé."""
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


def sqlstate(exc: BaseException) -> str | None:
    """Code SQLSTATE porté par une erreur SQLAlchemy, s'il y en a un.

    Sert à traduire un invariant refusé **par PostgreSQL** (trigger, contrainte) en
    erreur métier nommée. Le SQLSTATE est stable, contrairement au texte du message,
    qui dépend de la locale du serveur.
    """
    return getattr(getattr(exc, "orig", None), "sqlstate", None)


def constraint_name(exc: BaseException) -> str | None:
    """Nom de la contrainte ou de l'index violé, s'il y en a un.

    Jumeau de `sqlstate` pour les cas où le SQLSTATE seul ne suffit pas : plusieurs
    contraintes d'une même table rendent `23505`, et seul leur nom dit laquelle.
    PostgreSQL renseigne ce champ pour les index uniques comme pour les contraintes
    nommées. Il est stable, contrairement au texte du message.
    """
    return getattr(getattr(getattr(exc, "orig", None), "diag", None), "constraint_name", None)


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


class TemporaryPasswordExpiredError(CogesError):
    """Le bon mot de passe provisoire, mais passé son échéance (ADR 0078).

    Levée **après** la vérification du mot de passe : un mot de passe faux reste un
    simple « identifiants invalides », et l'échéance ne se révèle qu'à qui la connaît.
    """

    code = "temporary_password_expired"
    status_code = 401
    default_message = "Ce mot de passe provisoire a expiré. Demandez-en un nouveau au gérant."


class PermissionDeniedError(CogesError):
    code = "permission_denied"
    status_code = 403
    default_message = "Vous n'avez pas la permission d'effectuer cette action."


class ValidationFailedError(CogesError):
    code = "validation_failed"
    status_code = 422
    default_message = "Les données envoyées sont invalides."


class BusinessRuleError(CogesError):
    """Invariant métier violé par une demande pourtant bien formée.

    Chaque module en dérive **une classe par règle**, avec son propre code stable
    en anglais (`category_not_empty`, `insufficient_stock`…) et son message en
    français : le client peut alors réagir à la règle précise, pas à un
    « validation_failed » indifférencié.

    409 et non 422 : la donnée envoyée est valide, c'est l'état actuel du système
    qui rend l'opération impossible.
    """

    code = "business_rule_violated"
    status_code = 409
    default_message = "Cette opération est impossible dans l'état actuel des données."


class ConcurrentUpdateError(CogesError):
    """Interblocage (40P01) ou échec de sérialisation (40001) : rien n'a été écrit.

    La transaction a été annulée en entier par PostgreSQL ; recommencer le même geste
    est sans danger, et les écritures financières portent leur clé d'idempotence.
    """

    code = "concurrent_update"
    status_code = 409
    default_message = (
        "Quelqu'un modifiait la même chose au même moment. Rien n'a été enregistré : réessayez."
    )


#: SQLSTATE qui disent « recommencez », jamais « c'est cassé » (ADR 0088).
RETRYABLE_SQLSTATES = frozenset({"40P01", "40001"})


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


class RateLimitedError(CogesError):
    """Trop de requêtes dans la fenêtre courante (décision 16)."""

    code = "rate_limited"
    status_code = 429
    default_message = "Trop de requêtes. Réessayez dans quelques instants."

    def __init__(self, retry_after: int, *, scope: str) -> None:
        super().__init__(details={"scope": scope, "retry_after": retry_after})
        self.headers = {"Retry-After": str(retry_after)}


class PayloadTooLargeError(CogesError):
    """Corps de requête au-delà du plafond autorisé."""

    code = "payload_too_large"
    status_code = 413
    default_message = "La requête dépasse la taille maximale autorisée."


class FrontOutdatedError(CogesError):
    """Version du front trop ancienne pour cette API (ADR 0102) : il se met à jour."""

    code = "front_outdated"
    status_code = 426
    default_message = "Une nouvelle version de CoGes est prête."


class PasswordChangeRequiredError(CogesError):
    """Le compte doit d'abord remplacer son mot de passe provisoire (ADR 0074).

    Tant que c'est le cas, seules l'identité (`/auth/me`) et le changement de mot de
    passe (`/auth/password`) répondent : le gérant qui a donné le mot de passe le
    connaît, il ne doit pas servir à travailler.
    """

    code = "password_change_required"
    status_code = 409
    default_message = "Choisissez d'abord votre propre mot de passe."


class CompanySuspendedError(CogesError):
    """L'entreprise est suspendue par l'administration de la plateforme (ADR 0089).

    Ni « identifiants invalides » ni erreur technique : la personne a le bon mot de
    passe, c'est l'accès de l'entreprise qui est coupé, et elle doit savoir à qui
    s'adresser. Révélé seulement **après** le mot de passe vérifié.
    """

    code = "company_suspended"
    status_code = 403
    default_message = (
        "L'accès de votre entreprise à CoGes est suspendu. "
        "Contactez l'équipe CoGes pour le rétablir."
    )


class SupportReadOnlyError(PermissionDeniedError):
    """Une écriture tentée sous un jeton de support (ADR 0092) : refusée avant le handler,
    quelle que soit la route. L'accès support ne lit que."""

    code = "support_read_only"
    default_message = "L'accès support est en lecture seule : aucune modification possible."


class SupportSessionEndedError(AuthenticationRequiredError):
    """Session de support fermée, expirée, ou d'une autre entreprise (ADR 0092)."""

    code = "support_session_ended"
    default_message = "L'accès support est terminé."
