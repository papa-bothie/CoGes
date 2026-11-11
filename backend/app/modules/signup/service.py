"""Façade du module Signup : l'inscription libre-service (lot 30, ADR 0118).

Une **demande** n'est pas une boutique. Rien n'est créé chez les commerçants avant
l'activation, qui ne passe que par `activate_request` — appelée par le lien e-mail comme
par l'équipe — et qui fabrique l'entreprise par `onboard_company`, la même fonction que
la ligne de commande (`app.cli create-company`) : aucune seconde façon d'en créer une.

Deux chemins dans le même formulaire :

* avec un e-mail **et** un SMTP configuré, un lien de vérification part après le COMMIT
  (par le worker, qui tire lui-même le jeton : il ne transite jamais par la file) ; le
  clic active la boutique ;
* sinon, la demande attend l'équipe, qui contacte le commerçant et active.

Point d'extension : un futur « code WhatsApp » sera un troisième `path`, avec sa propre
table de codes et sa fonction de consommation, qui aboutira au même `activate_request`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from app.core import legal, mailer, queue
from app.core.config import get_settings
from app.core.errors import (
    BusinessRuleError,
    NotFoundError,
    SignupLinkInvalidError,
)
from app.core.phone import stored_form, to_e164
from app.core.security import hash_password
from app.core.tenancy import TenantContext, on_commit, tenant_transaction
from app.modules.companies import service as companies_service
from app.modules.rbac import service as rbac_service
from app.modules.rbac.matrix import MANAGER
from app.modules.signup import limits
from app.modules.signup import repository as repo
from app.modules.signup.schemas import (
    KnownAccount,
    SignupConfig,
    SignupNeutral,
    SignupRequestAccepted,
    SignupRequestCreate,
    SignupRequestPage,
    SignupRequestRead,
    SignupStats,
    SignupVerified,
)
from app.modules.users import service as users_service
from app.modules.users.schemas import UserCreate

logger = logging.getLogger(__name__)

#: Tâches du worker (`app/workers/tasks/signup.py`), désignées par leur nom.
SEND_VERIFICATION_TASK = "signup.send_verification"
ALREADY_REGISTERED_TASK = "signup.already_registered"
WELCOME_TASK = "signup.welcome"
NOTIFY_TEAM_TASK = "signup.notify_team"
AUTOMATIC_CAP_TASK = "signup.automatic_cap_reached"

MESSAGE_EMAIL = "Vérifiez votre boîte e-mail : cliquez sur le lien pour ouvrir votre boutique."
MESSAGE_TEAM = "Demande reçue. Nous vous contactons sur WhatsApp sous 24 h."
MESSAGE_RESEND = "Si une demande attend cette adresse, un nouveau lien vient de partir."
MESSAGE_CONTACT_TEAM = "C'est noté : nous vous contactons sur WhatsApp sous 24 h."
MESSAGE_READY = "Votre boutique est prête. Connectez-vous avec votre e-mail ou votre numéro."
MESSAGE_VERIFIED_TEAM = (
    "Votre adresse est vérifiée. Nous finissons d'ouvrir votre boutique et vous contactons "
    "sur WhatsApp."
)

#: Contexte des transactions sans entreprise (routes publiques, connexion) : la RLS ne
#: laisse rien voir chez les commerçants ; seules les fonctions de `coges_signup` servent.
_NO_COMPANY = UUID(int=0)

#: Codes de boutique jamais attribués : adresses, comptes de démonstration, mots du métier.
RESERVED_SLUGS = frozenset(
    {
        "admin",
        "administration",
        "api",
        "app",
        "aide",
        "assistance",
        "cgu",
        "cgv",
        "conditions",
        "confidentialite",
        "coges",
        "compte",
        "connexion",
        "contact",
        "demo",
        "demo-front",
        "dev",
        "e2e",
        "equipe",
        "help",
        "inscription",
        "login",
        "maquette",
        "mail",
        "platform",
        "plateforme",
        "root",
        "staging",
        "preprod",
        "status",
        "support",
        "system",
        "systeme",
        "test",
        "verification",
        "www",
    }
)
SLUG_MIN = 3
SLUG_MAX = 40


class SignupNotPendingError(BusinessRuleError):
    code = "signup_not_pending"
    default_message = "Cette demande n'est plus en attente : elle a déjà été activée ou refusée."


class SignupSlugUnavailableError(BusinessRuleError):
    code = "signup_slug_unavailable"
    default_message = "Impossible de trouver un code de boutique libre pour ce nom."


@dataclass(frozen=True, slots=True)
class ActivatedShop:
    company_id: UUID
    manager_id: UUID
    company_slug: str


def token_digest(token: str) -> str:
    """Empreinte sha256 d'un jeton : seule elle est stockée."""
    return hashlib.sha256(token.encode()).hexdigest()


@lru_cache(maxsize=1)
def disposable_domains() -> frozenset[str]:
    """Courte liste d'adresses jetables, maintenue dans le dépôt : chemin de l'équipe."""
    source = Path(__file__).with_name("disposable_domains.txt")
    lines = source.read_text(encoding="utf-8").splitlines()
    return frozenset(
        line.strip().lower() for line in lines if line.strip() and not line.startswith("#")
    )


def is_disposable(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower()
    return any(domain == item or domain.endswith(f".{item}") for item in disposable_domains())


def config() -> SignupConfig:
    settings = get_settings()
    return SignupConfig(
        enabled=settings.signup_enabled,
        instant_with_email=settings.signup_enabled and mailer.is_configured(),
        support_whatsapp=settings.support_whatsapp,
        resend_interval_seconds=settings.signup_resend_interval_seconds,
    )


def _public_transaction() -> Any:
    return tenant_transaction(TenantContext.bootstrap(_NO_COMPANY))


def _accepted(path: str) -> SignupRequestAccepted:
    return SignupRequestAccepted(
        path="email" if path == "email" else "team",
        message=MESSAGE_EMAIL if path == "email" else MESSAGE_TEAM,
    )


def create_request(
    payload: SignupRequestCreate, *, ip_address: str | None
) -> SignupRequestAccepted:
    """Enregistre une demande et rend une réponse **neutre** pour son chemin."""
    wants_email = payload.email is not None and mailer.is_configured()
    # Champ piège : un robot l'a rempli. Même réponse, rien n'est écrit ni compté.
    if payload.website:
        return _accepted("email" if wants_email else "team")

    ip_hash = limits.ip_fingerprint(ip_address)
    limits.check_request(ip_hash=ip_hash, phone=payload.phone, email=payload.email)

    path = "email" if wants_email else "team"
    cap_reached = False
    if path == "email" and payload.email is not None and is_disposable(payload.email):
        path = "team"
    elif path == "email" and not limits.take_automatic_slot():
        path, cap_reached = "team", True

    password_hash = hash_password(payload.password)
    with _public_transaction() as session:
        # Un e-mail déjà inscrit n'ouvre jamais une seconde boutique : l'e-mail envoyé le
        # dit et propose la connexion. Même réponse que pour une adresse nouvelle.
        if path == "email" and repo.known(session, email=payload.email, phone=None):
            email = payload.email
            on_commit(session, lambda: _enqueue(ALREADY_REGISTERED_TASK, email=email))
            return _accepted("email")
        created = repo.create(
            session,
            shop_name=payload.shop_name,
            full_name=payload.full_name,
            phone=payload.phone,
            email=payload.email,
            password_hash=password_hash,
            legal_version=legal.LEGAL_VERSION,
            ip_hash=ip_hash,
            path=path,
        )
        request_id = created.request_id
        if created.path == "email" and mailer.is_configured():
            on_commit(session, lambda: _enqueue(SEND_VERIFICATION_TASK, request_id=str(request_id)))
        if created.created and created.path == "team":
            on_commit(session, lambda: _enqueue(NOTIFY_TEAM_TASK, request_id=str(request_id)))
    if cap_reached:
        _enqueue(AUTOMATIC_CAP_TASK)
    return _accepted(path)


def _enqueue(task: str, **kwargs: Any) -> None:
    """Après le COMMIT seulement (ADR 0079) ; une file indisponible ne défait rien."""
    if not queue.enqueue(task, **kwargs):
        logger.warning("Tâche d'inscription non déposée", extra={"task": task})


def issue_verification(request_id: UUID) -> tuple[str, str, str] | None:
    """Worker : tire un jeton, en garde l'empreinte, rend (jeton, e-mail, boutique).

    Le jeton naît ici, dans le worker : il ne passe ni par la file ni par l'API.
    """
    token = secrets.token_urlsafe(32)
    ttl = timedelta(hours=get_settings().signup_token_ttl_hours)
    with _public_transaction() as session:
        target = repo.issue_token(session, request_id, token_digest(token), ttl)
    if target is None:
        return None
    email, shop_name = target
    return token, email, shop_name


def verification_link(token: str) -> str:
    return f"{get_settings().merchant_url.rstrip('/')}/verification/{token}"


def verify(token: str, *, ip_address: str | None) -> SignupVerified:
    """Lien e-mail : jeton à usage unique, puis activation immédiate."""
    company_id, manager_id = uuid4(), uuid4()
    ctx = TenantContext(user_id=manager_id, company_id=company_id)
    switched_to_team: UUID | None = None
    shop: ActivatedShop | None = None
    with tenant_transaction(ctx) as session:
        request_id = repo.consume_token(session, token_digest(token))
        if request_id is None:
            raise SignupLinkInvalidError()
        reserved = repo.reserve(session, request_id)
        if reserved is None:
            raise SignupLinkInvalidError()
        # Un numéro déjà inscrit ne s'active pas tout seul : l'équipe voit la demande
        # (« déjà connu : boutique X ») et décide. L'adresse, elle, reste vérifiée.
        if repo.known(session, email=reserved.email, phone=stored_form(reserved.phone)):
            if reserved.email is not None:
                repo.switch_to_team(session, reserved.email)
            switched_to_team = request_id
        else:
            shop = _activate_reserved(
                session, ctx, request_id, reserved, actor=None, via="email_link", ip=ip_address
            )
    if switched_to_team is not None:
        _enqueue(NOTIFY_TEAM_TASK, request_id=str(switched_to_team))
        return SignupVerified(status="team", message=MESSAGE_VERIFIED_TEAM)
    assert shop is not None  # noqa: S101 - l'une des deux branches a été prise
    return SignupVerified(status="ready", company_slug=shop.company_slug, message=MESSAGE_READY)


def activate_request(
    request_id: UUID, *, actor: UUID | None, via: str, ip_address: str | None
) -> ActivatedShop:
    """L'unique activation (ADR 0118). Une transaction, idempotente : la demande est
    verrouillée d'abord, et une demande déjà décidée n'ouvre rien (409)."""
    ctx = TenantContext(user_id=uuid4(), company_id=uuid4())
    with tenant_transaction(ctx) as session:
        reserved = repo.reserve(session, request_id)
        if reserved is None:
            raise SignupNotPendingError()
        return _activate_reserved(
            session, ctx, request_id, reserved, actor=actor, via=via, ip=ip_address
        )


def _activate_reserved(
    session: Session,
    ctx: TenantContext,
    request_id: UUID,
    reserved: repo.ReservedRequest,
    *,
    actor: UUID | None,
    via: str,
    ip: str | None,
) -> ActivatedShop:
    email = reserved.email if reserved.email_verified else None
    manager = UserCreate(
        email=email,
        phone=stored_form(reserved.phone),
        full_name=reserved.full_name,
        password=None,
        role_ids=[],
    )
    company = onboard_company(
        session,
        ctx,
        name=reserved.shop_name,
        slug=None,
        manager=manager,
        password_hash=reserved.password_hash,
    )
    users_service.record_legal_acceptance(
        session,
        ctx,
        ctx.user_id,
        version=reserved.legal_version,
        accepted_at=reserved.legal_accepted_at,
    )
    if not repo.mark_activated(
        session, request_id, company.id, actor=actor, via=via, ip_address=ip
    ):
        raise SignupNotPendingError()
    shop = ActivatedShop(company_id=company.id, manager_id=ctx.user_id, company_slug=company.slug)
    if email is not None:
        on_commit(
            session,
            lambda: _enqueue(
                WELCOME_TASK, company_id=str(shop.company_id), user_id=str(shop.manager_id)
            ),
        )
    return shop


def onboard_company(
    session: Session,
    ctx: TenantContext,
    *,
    name: str,
    slug: str | None,
    manager: UserCreate,
    password_hash: str | None = None,
    currency: str = "XOF",
    timezone: str = "Africa/Dakar",
) -> Any:
    """Entreprise, rôles système et gérant, dans la transaction de l'appelant.

    La seule façon de fabriquer une entreprise (ADR 0009, 0118), pour la ligne de commande
    comme pour l'inscription. `ctx` porte l'`id` pré-généré de l'entreprise et celui du
    gérant (ADR 0004). Sans `slug`, il est tiré du nom, avec un suffixe s'il est pris ;
    l'essai de 30 jours naît avec l'entreprise (trigger de l'ADR 0091).
    """
    if slug is not None:
        company = companies_service.create_company(
            session, ctx, name=name, slug=slug, currency=currency, timezone=timezone
        )
    else:
        company = _create_with_free_slug(session, ctx, name, currency=currency, timezone=timezone)
    roles = rbac_service.create_system_roles(session, ctx)
    # Même façade que l'écran Personnes : mêmes contrôles d'unicité, mêmes messages. Sans
    # rôle ici : le gérant n'existe pas encore pour déléguer.
    user, _ = users_service.create_user(
        session, ctx, manager, user_id=ctx.user_id, password_hash=password_hash
    )
    # L'auteur de l'audit est le gérant lui-même, déjà écrit (flush) en base.
    rbac_service.assign_role(session, ctx, user.id, roles[MANAGER].id)
    return company


def slug_candidates(name: str) -> list[str]:
    """Codes de boutique tirés du nom, du plus simple au plus suffixé."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:SLUG_MAX].strip("-")
    if len(base) < SLUG_MIN:
        base = f"boutique-{base}".strip("-") if base else "boutique"
    stem = base[: SLUG_MAX - 5].strip("-")
    candidates = [] if base in RESERVED_SLUGS else [base]
    candidates += [f"{stem}-{number}" for number in range(2, 10)]
    candidates += [f"{stem}-{secrets.token_hex(2)}" for _ in range(5)]
    return candidates


def _create_with_free_slug(
    session: Session, ctx: TenantContext, name: str, *, currency: str, timezone: str
) -> Any:
    for candidate in slug_candidates(name):
        try:
            with session.begin_nested():
                return companies_service.create_company(
                    session, ctx, name=name, slug=candidate, currency=currency, timezone=timezone
                )
        except IntegrityError:
            # Code déjà pris (l'index unique voit toutes les entreprises, la RLS non) : le
            # suivant. Le point de sauvegarde défait aussi l'essai créé avec elle.
            continue
    raise SignupSlugUnavailableError()


def resend(email: str) -> SignupNeutral:
    """« Renvoyer le lien » : même réponse, qu'une demande attende cette adresse ou non."""
    limits.check_resend(email)
    with _public_transaction() as session:
        request_id = repo.resend_target(session, email)
    if request_id is not None and mailer.is_configured():
        _enqueue(SEND_VERIFICATION_TASK, request_id=str(request_id))
    return SignupNeutral(message=MESSAGE_RESEND)


def contact_team(email: str) -> SignupNeutral:
    """« Je n'ai pas reçu l'e-mail : être contacté sur WhatsApp »."""
    limits.check_resend(email)
    with _public_transaction() as session:
        request_id = repo.switch_to_team(session, email)
    if request_id is not None:
        _enqueue(NOTIFY_TEAM_TASK, request_id=str(request_id))
    return SignupNeutral(message=MESSAGE_CONTACT_TEAM)


def pending_login(identifier: str) -> repo.PendingLogin | None:
    """Connexion sans compte (ADR 0118) : la demande en attente de cet identifiant (e-mail
    ou numéro, lu par la même fonction que l'inscription), s'il y en a une. Rien n'est dit
    avant que la connexion n'ait vérifié son mot de passe."""
    is_email = "@" in identifier
    email = identifier.strip().lower() if is_email else None
    phone = None if is_email else to_e164(identifier)
    if email is None and phone is None:
        return None
    with _public_transaction() as session:
        pending = repo.pending_for_login(session, email=email, phone=phone)
    return pending[0] if pending else None


# --- Administration ---------------------------------------------------------------------


def _read(row: Any, known: list[Any] | None = None) -> SignupRequestRead:
    return SignupRequestRead(
        id=row.id,
        shop_name=row.shop_name,
        full_name=row.full_name,
        phone=row.phone,
        email=None if row.email is None else str(row.email),
        path=row.path,
        status=row.status,
        email_verified_at=row.email_verified_at,
        reject_reason=row.reject_reason,
        team_note=row.team_note,
        created_at=row.created_at,
        path_changed_at=row.path_changed_at,
        decided_at=row.decided_at,
        decided_via=row.decided_via,
        company_id=row.activated_company_id,
        company_slug=row.company_slug,
        legal_version=row.legal_version,
        purged=row.purged_at is not None,
        known_accounts=[
            KnownAccount(
                company_id=item.company_id,
                company_name=item.company_name,
                company_slug=item.company_slug,
                matched_on=item.matched_on,
            )
            for item in known or []
        ],
    )


def _known(session: Session, row: Any) -> list[Any]:
    if row.phone is None and row.email is None:
        return []
    return repo.known_accounts(
        session,
        email=None if row.email is None else str(row.email),
        phone=stored_form(row.phone),
    )


def list_requests(
    session: Session,
    *,
    status: str | None,
    path: str | None,
    older_than_hours: int | None,
    page: int,
    page_size: int,
) -> SignupRequestPage:
    older_than = datetime.now(UTC) - timedelta(hours=older_than_hours) if older_than_hours else None
    rows, total = repo.list_requests(
        session, status=status, path=path, older_than=older_than, page=page, page_size=page_size
    )
    return SignupRequestPage(
        items=[_read(row, _known(session, row)) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        team_queue=repo.team_queue_size(session),
        smtp_configured=mailer.is_configured(),
    )


def get_request(session: Session, request_id: UUID) -> SignupRequestRead:
    row = repo.get_request(session, request_id)
    if row is None:
        raise NotFoundError("Demande introuvable.")
    return _read(row, _known(session, row))


_PLATFORM_AUDIT = text(
    """
    INSERT INTO platform_audit_logs (actor_id, action, entity_table, entity_id, diff, ip_address)
    VALUES (:actor, 'update', 'signup_requests', :id, CAST(:diff AS jsonb), CAST(:ip AS inet))
    """
)


def _audit(
    session: Session, actor: UUID, request_id: UUID, diff: str, ip_address: str | None
) -> None:
    session.execute(
        _PLATFORM_AUDIT, {"actor": actor, "id": request_id, "diff": diff, "ip": ip_address}
    )


def reject(
    session: Session,
    request_id: UUID,
    *,
    actor: UUID,
    reason: str,
    note: str | None,
    ip_address: str | None,
) -> SignupRequestRead:
    row = repo.get_request(session, request_id, lock=True)
    if row is None:
        raise NotFoundError("Demande introuvable.")
    if row.status != "pending":
        raise SignupNotPendingError()
    repo.reject(session, request_id, actor=actor, reason=reason, note=note)
    _audit(
        session,
        actor,
        request_id,
        json.dumps(
            {"before": {"status": "pending"}, "after": {"status": "rejected", "reason": reason}}
        ),
        ip_address,
    )
    return get_request(session, request_id)


def set_note(
    session: Session, request_id: UUID, *, actor: UUID, note: str, ip_address: str | None
) -> SignupRequestRead:
    row = repo.get_request(session, request_id, lock=True)
    if row is None:
        raise NotFoundError("Demande introuvable.")
    repo.set_note(session, request_id, note)
    # Le texte de la note n'entre pas dans le journal : seulement le fait.
    _audit(session, actor, request_id, json.dumps({"after": {"team_note": "modifiée"}}), ip_address)
    return get_request(session, request_id)


def stats(session: Session, *, days: int) -> SignupStats:
    row = repo.stats(session, since=datetime.now(UTC) - timedelta(days=days))
    return SignupStats(
        received_email=row.received_email,
        received_team=row.received_team,
        activated_by_link=row.activated_by_link,
        activated_by_team=row.activated_by_team,
        rejected=row.rejected,
        abandoned=row.abandoned,
        pending_team=row.pending_team,
        pending_email=row.pending_email,
        average_hours_to_activation=(
            None if row.average_hours is None else round(float(row.average_hours), 1)
        ),
        smtp_configured=mailer.is_configured(),
    )


@dataclass(frozen=True, slots=True)
class Maintenance:
    switched_to_team: int
    abandoned: int
    purged: int


def maintenance(session: Session) -> Maintenance:
    """Tâche de fond (beat) : bascule à 48 h, abandon à 7 jours, effacement à 30 jours.

    Idempotente : chaque mise à jour ne vise que les lignes pas encore traitées.
    """
    settings = get_settings()
    return Maintenance(
        switched_to_team=repo.switch_stale_to_team(
            session, after=timedelta(hours=settings.signup_team_after_hours)
        ),
        abandoned=repo.abandon_stale(
            session, after=timedelta(days=settings.signup_abandon_after_days)
        ),
        purged=repo.purge_personal_data(
            session, after=timedelta(days=settings.signup_purge_after_days)
        ),
    )


def manager_contact(company_id: UUID, user_id: UUID) -> tuple[str | None, str]:
    """Worker : l'e-mail du nouveau gérant et le code de sa boutique (bienvenue)."""
    ctx = TenantContext(user_id=user_id, company_id=company_id)
    with tenant_transaction(ctx) as session:
        user = users_service.get_user(session, ctx, user_id)
        company = companies_service.get_current_company(session, ctx)
        return user.email, company.slug
