"""Façade de services du module RBAC.

Tout changement de rôle ou de permission est une **élévation de privilège
potentielle** : il passe par un audit critique, dans la transaction (décision 05).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.audit import AuditAction, audit_critical
from app.core.errors import (
    BusinessRuleError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.core.tenancy import TenantContext
from app.modules.rbac.matrix import (
    ABILITIES,
    GRID_ROLES,
    LOCKED_ABILITIES,
    MANAGER,
    SYSTEM_ROLE_LABELS,
    SYSTEM_ROLES,
)
from app.modules.rbac.models import Role
from app.modules.rbac.repository import (
    PermissionCatalogue,
    RolePermissionRepository,
    RoleRepository,
    UserRoleRepository,
)
from app.modules.rbac.schemas import (
    AbilityGrid,
    AbilityRead,
    RoleAbilities,
    RoleCreate,
    RoleUpdate,
)


class RoleLockedError(BusinessRuleError):
    code = "role_locked"
    default_message = "Le gérant garde tous les droits : sa colonne ne se modifie pas."


def permission_codes_for_user(session: Session, ctx: TenantContext, user_id: UUID) -> list[str]:
    """Permissions effectives d'un utilisateur, par ses rôles."""
    return UserRoleRepository(session, ctx).permission_codes_for_user(user_id)


def roles_for_user(session: Session, ctx: TenantContext, user_id: UUID) -> Sequence[Role]:
    """Rôles d'un utilisateur du tenant courant."""
    return RoleRepository(session, ctx).for_user(user_id)


def roles_by_user(
    session: Session, ctx: TenantContext, user_ids: Sequence[UUID]
) -> dict[UUID, list[Role]]:
    """Rôles d'une page d'utilisateurs, groupés par utilisateur (une seule requête)."""
    grouped: dict[UUID, list[Role]] = {user_id: [] for user_id in user_ids}
    for user_id, role in RoleRepository(session, ctx).for_users(user_ids):
        grouped.setdefault(user_id, []).append(role)
    return grouped


def system_role_id(session: Session, ctx: TenantContext, name: str) -> UUID | None:
    """Identifiant d'un rôle système de l'entreprise (`gerant`…), ou `None`."""
    role = RoleRepository(session, ctx).get_by_name(name)
    return role.id if role is not None and role.is_system else None


def holders_of_role(session: Session, ctx: TenantContext, role_id: UUID) -> list[UUID]:
    """Utilisateurs portant ce rôle, actifs ou non (l'activité appartient à Users)."""
    return UserRoleRepository(session, ctx).user_ids_with_role(role_id)


def list_roles(
    session: Session, ctx: TenantContext, *, page: int, page_size: int
) -> tuple[Sequence[Role], int]:
    repository = RoleRepository(session, ctx)
    return repository.page(page=page, page_size=page_size), repository.count()


def get_role(session: Session, ctx: TenantContext, role_id: UUID) -> Role:
    """Rôle du tenant courant. Celui d'une autre entreprise est introuvable : 404."""
    role = RoleRepository(session, ctx).get(role_id)
    if role is None:
        raise NotFoundError("Rôle introuvable.")
    return role


def role_label(role: Role) -> str:
    """« Vendeur » pour un rôle système, son nom tel quel pour un rôle sur mesure."""
    return SYSTEM_ROLE_LABELS.get(role.name, role.name) if role.is_system else role.name


def role_permissions(session: Session, ctx: TenantContext, role_id: UUID) -> list[str]:
    return RolePermissionRepository(session, ctx).codes_for_role(role_id)


def _resolve_permission_ids(session: Session, codes: Sequence[str]) -> list[UUID]:
    """Traduit des codes en identifiants, en refusant tout code inconnu."""
    found = PermissionCatalogue(session).by_codes(codes)
    known = {permission.code: permission.id for permission in found}
    unknown = sorted(set(codes) - known.keys())
    if unknown:
        raise ValidationFailedError(
            "Permissions inconnues.", details={"unknown_permissions": unknown}
        )
    return [known[code] for code in codes]


#: Droits réservés au rôle gérant (ADR 0075, 0088) : qui gère les personnes ou les rôles
#: peut se donner tout le reste. Le verrou de la grille vaut pour toutes les routes.
_MANAGER_ONLY_PREFIXES = ("users:", "roles:")
#: Les réglages de l'entreprise et la santé du système restent eux aussi au gérant
#: (ADR 0007, 0032) : ligne verrouillée de la grille, refusée à un rôle sur mesure (0099).
_MANAGER_ONLY_CODES = frozenset({"company:update", "system:read"})


def _assert_no_manager_only_rights(codes: Sequence[str]) -> None:
    reserved = sorted(
        code
        for code in codes
        if code.startswith(_MANAGER_ONLY_PREFIXES) or code in _MANAGER_ONLY_CODES
    )
    if reserved:
        raise ValidationFailedError(
            "Gérer les personnes et les rôles reste réservé au gérant.",
            details={"reserved_permissions": reserved},
        )


def assert_delegable(session: Session, ctx: TenantContext, role_id: UUID) -> None:
    """Refuse d'attribuer un rôle qui donne plus que les droits de l'appelant (ADR 0088).

    Sans ce contrôle, qui peut créer des comptes peut créer un gérant. Le contexte de
    la requête porte les droits relus en base (`deps.py`), jamais ceux du client.
    """
    get_role(session, ctx, role_id)  # 404 si le rôle appartient à une autre entreprise
    beyond = sorted(set(role_permissions(session, ctx, role_id)) - ctx.permissions)
    if beyond:
        raise PermissionDeniedError(
            "Ce rôle donne plus de droits que les vôtres : demandez au gérant.",
            details={"permissions": beyond},
        )


def create_role(
    session: Session,
    ctx: TenantContext,
    payload: RoleCreate,
    *,
    ip_address: str | None = None,
) -> Role:
    """Crée un rôle personnalisé et lui attache ses permissions."""
    repository = RoleRepository(session, ctx)
    if repository.get_by_name(payload.name) is not None:
        raise ValidationFailedError("Un rôle porte déjà ce nom.", details={"name": payload.name})

    _assert_no_manager_only_rights(payload.permissions)
    permission_ids = _resolve_permission_ids(session, payload.permissions)
    role = repository.add(
        Role(
            company_id=ctx.company_id,
            name=payload.name,
            description=payload.description,
            is_system=False,
        )
    )
    session.flush()
    RolePermissionRepository(session, ctx).replace(role.id, permission_ids)

    audit_critical(
        session,
        ctx,
        action=AuditAction.INSERT,
        entity_table="roles",
        entity_id=role.id,
        before=None,
        after={"name": role.name, "permissions": sorted(payload.permissions)},
        ip_address=ip_address,
    )
    return role


def update_role(
    session: Session,
    ctx: TenantContext,
    role_id: UUID,
    payload: RoleUpdate,
    *,
    ip_address: str | None = None,
) -> Role:
    """Modifie la description ou la matrice d'un rôle."""
    role = get_role(session, ctx, role_id)
    link_repository = RolePermissionRepository(session, ctx)
    before = {
        "description": role.description,
        "permissions": link_repository.codes_for_role(role_id),
    }

    if payload.description is not None:
        role.description = payload.description
    if payload.permissions is not None:
        if role.is_system:
            raise ValidationFailedError("Les permissions d'un rôle système ne se modifient pas.")
        _assert_no_manager_only_rights(payload.permissions)
        link_repository.replace(role_id, _resolve_permission_ids(session, payload.permissions))
    session.flush()

    after = {
        "description": role.description,
        "permissions": link_repository.codes_for_role(role_id),
    }
    audit_critical(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_table="roles",
        entity_id=role.id,
        before=before,
        after=after,
        ip_address=ip_address,
    )
    return role


def delete_role(
    session: Session, ctx: TenantContext, role_id: UUID, *, ip_address: str | None = None
) -> None:
    """Supprime un rôle sans porteur. Un rôle système n'est jamais supprimable."""
    role = get_role(session, ctx, role_id)
    if role.is_system:
        raise ValidationFailedError("Un rôle système ne peut pas être supprimé.")

    link_repository = RolePermissionRepository(session, ctx)
    before = {"name": role.name, "permissions": link_repository.codes_for_role(role_id)}
    link_repository.replace(role_id, [])

    audit_critical(
        session,
        ctx,
        action=AuditAction.DELETE,
        entity_table="roles",
        entity_id=role.id,
        before=before,
        after=None,
        ip_address=ip_address,
    )
    # Après l'audit : si la FK ON DELETE RESTRICT refuse, toute la transaction tombe.
    RoleRepository(session, ctx).delete(role)
    session.flush()


def assign_role(
    session: Session,
    ctx: TenantContext,
    user_id: UUID,
    role_id: UUID,
    *,
    ip_address: str | None = None,
) -> list[UUID]:
    """Attribue un rôle à un utilisateur du même tenant."""
    get_role(session, ctx, role_id)  # 404 si le rôle appartient à une autre entreprise
    repository = UserRoleRepository(session, ctx)
    before = repository.role_ids_for_user(user_id)
    if role_id in before:
        return before

    repository.grant(user_id, role_id)
    session.flush()
    after = repository.role_ids_for_user(user_id)

    audit_critical(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_table="user_roles",
        entity_id=user_id,
        before={"role_ids": before},
        after={"role_ids": after},
        ip_address=ip_address,
    )
    return after


def revoke_role(
    session: Session,
    ctx: TenantContext,
    user_id: UUID,
    role_id: UUID,
    *,
    ip_address: str | None = None,
) -> list[UUID]:
    """Retire un rôle. La trace reste dans `audit_logs` (ADR 0007)."""
    repository = UserRoleRepository(session, ctx)
    before = repository.role_ids_for_user(user_id)
    if repository.revoke(user_id, role_id) == 0:
        raise NotFoundError("Ce rôle n'est pas attribué à cet utilisateur.")
    session.flush()
    after = repository.role_ids_for_user(user_id)

    audit_critical(
        session,
        ctx,
        action=AuditAction.UPDATE,
        entity_table="user_roles",
        entity_id=user_id,
        before={"role_ids": before},
        after={"role_ids": after},
        ip_address=ip_address,
    )
    return after


def create_system_roles(session: Session, ctx: TenantContext) -> dict[str, Role]:
    """Crée les trois rôles système de l'entreprise (ADR 0007).

    Appelée à la création d'une entreprise. Le gérant reçoit **tout** le catalogue.
    """
    catalogue = PermissionCatalogue(session)
    every_code = [permission.code for permission in catalogue.all()]
    role_repository = RoleRepository(session, ctx)
    link_repository = RolePermissionRepository(session, ctx)

    created: dict[str, Role] = {}
    for name, codes in SYSTEM_ROLES.items():
        role = role_repository.add(
            Role(
                company_id=ctx.company_id,
                name=name,
                description=SYSTEM_ROLE_LABELS[name],
                is_system=True,
            )
        )
        session.flush()
        wanted = every_code if codes is None else sorted(codes)
        link_repository.replace(role.id, _resolve_permission_ids(session, wanted))
        created[name] = role

    session.flush()
    return created


def user_ids_with_permission(session: Session, ctx: TenantContext, code: str) -> list[UUID]:
    """Utilisateurs détenant ce droit — sans distinguer actifs et désactivés.

    Façade lecture seule pour la bande E (ADR 0032). Alerter par **droit** plutôt que
    par nom de rôle survit aux rôles personnalisés : c'est la même matrice qui décide
    qui peut annuler une vente et qui apprend qu'une vente a été annulée.

    Le tri entre comptes actifs et désactivés appartient à Users : l'appelant compose
    les deux façades, RBAC ne joint pas la table d'un autre module.
    """
    return UserRoleRepository(session, ctx).user_ids_with_permission(code)


# ------------------------------------------------------------ grille (ADR 0075)


def _checked(codes: set[str]) -> list[str]:
    """Lignes cochées : celles dont le rôle porte toutes les permissions."""
    return [key for key, (_, needed) in ABILITIES.items() if needed <= codes]


def _partial(codes: set[str]) -> list[str]:
    """Lignes « en partie » : le rôle en porte certains droits, pas tous (ADR 0099).

    Un droit partagé avec une ligne cochée ne compte pas : « Encaisser une dette »
    n'est pas en partie parce que « Voir l'argent » donne `debts:read`.
    """
    full = set().union(*(ABILITIES[key][1] for key in _checked(codes)))
    return [
        key
        for key, (_, needed) in ABILITIES.items()
        if not needed <= codes and (needed & codes) - full
    ]


def ability_grid(session: Session, ctx: TenantContext) -> AbilityGrid:
    """La grille « Qui peut faire quoi » des trois rôles système, dans cet ordre."""
    repository = RoleRepository(session, ctx)
    links = RolePermissionRepository(session, ctx)
    roles: list[RoleAbilities] = []
    for name in GRID_ROLES:
        role = repository.get_by_name(name)
        if role is None or not role.is_system:
            continue
        roles.append(
            RoleAbilities(
                role_id=role.id,
                name=role.name,
                label=SYSTEM_ROLE_LABELS[name],
                locked=name == MANAGER,
                abilities=_checked(codes := set(links.codes_for_role(role.id))),
                partial=_partial(codes),
            )
        )
    return AbilityGrid(
        abilities=[
            AbilityRead(
                key=key, label=label, permissions=sorted(needed), locked=key in LOCKED_ABILITIES
            )
            for key, (label, needed) in ABILITIES.items()
        ],
        roles=roles,
    )


def set_role_abilities(
    session: Session,
    ctx: TenantContext,
    role_id: UUID,
    abilities: Sequence[str],
    *,
    ip_address: str | None = None,
) -> RoleAbilities:
    """Coche exactement ces lignes pour un rôle ; ses droits hors grille ne bougent pas.

    Nouvelle matrice = (droits actuels − droits de toutes les lignes) ∪ droits des
    lignes cochées ∪ droits déjà portés des lignes « en partie » non cochées, **moins**
    ceux des lignes que l'on décoche : une ligne incomplète garde ce qu'elle a tant que
    le gérant n'y touche pas, et à l'écran on la coche d'abord, puis on la décoche
    entière (ADR 0099) — un droit partagé avec une ligne « en partie » part aussi, sans
    quoi le second appui laisserait la ligne « en partie » (ADR 0103). Aucun droit n'est
    jamais ajouté qu'une ligne cochée ne demande. Le gérant est refusé (409) ; une ligne
    verrouillée garde l'état qu'elle avait. Le rôle est verrouillé : deux enregistrements
    simultanés se suivent. Audit critique, comme toute modification de rôle.
    """
    role = RoleRepository(session, ctx).get_for_update(role_id)
    if role is None:
        raise NotFoundError("Rôle introuvable.")
    if role.name == MANAGER and role.is_system:
        raise RoleLockedError()
    wanted = set(abilities)
    unknown = sorted(wanted - ABILITIES.keys())
    if unknown or len(wanted) != len(abilities):
        raise ValidationFailedError(
            "Lignes inconnues ou en double.", details={"abilities": unknown or list(abilities)}
        )

    links = RolePermissionRepository(session, ctx)
    before = set(links.codes_for_role(role_id))
    previously = set(_checked(before))
    if (wanted ^ previously) & LOCKED_ABILITIES:
        raise ValidationFailedError(
            "Les lignes verrouillées ne se changent pas depuis la grille.",
            details={"abilities": sorted(LOCKED_ABILITIES)},
        )

    grid = set().union(*(needed for _, needed in ABILITIES.values()))
    after = (before - grid).union(*(ABILITIES[key][1] for key in wanted))
    # Les droits des lignes décochées partent, sauf ceux qu'une ligne cochée demande.
    dropped = set().union(*(ABILITIES[key][1] for key in previously - wanted))
    # Une ligne verrouillée non cochée, ou « en partie » et laissée telle quelle, garde
    # ses droits partiels — hors ceux d'une ligne que l'on vient de décocher.
    for key in (LOCKED_ABILITIES | set(_partial(before))) - wanted:
        after |= (before & ABILITIES[key][1]) - dropped
    if after != before:
        links.replace(role_id, _resolve_permission_ids(session, sorted(after)))
        session.flush()
        audit_critical(
            session,
            ctx,
            action=AuditAction.UPDATE,
            entity_table="roles",
            entity_id=role.id,
            before={"permissions": sorted(before), "abilities": sorted(previously)},
            after={"permissions": sorted(after), "abilities": sorted(wanted)},
            ip_address=ip_address,
        )
    return RoleAbilities(
        role_id=role.id,
        name=role.name,
        label=role_label(role),
        locked=False,
        abilities=_checked(after),
        partial=_partial(after),
    )
