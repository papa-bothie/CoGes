"""Commandes d'administration de CoGes.

L'inscription publique n'existe pas en V1 (ADR 0009) : une entreprise est créée par
cette commande, qui pose l'entreprise, ses trois rôles système et son gérant, **dans
une seule transaction**.

    python -m app.cli create-company \\
        --name "Boutique Diallo" --slug boutique-diallo \\
        --manager-email gerant@example.test --manager-name "Awa Diallo"

Un gérant sans e-mail se crée avec son téléphone (`--manager-phone "77 123 45 67"`),
ou avec les deux ; l'un des deux au moins est exigé. Le numéro est ramené à ses
chiffres comme à la connexion (ADR 0074) : il se tape ensuite sous n'importe quelle
forme (« +221 77 123 45 67 », « 221771234567 »).

Le mot de passe est demandé de façon interactive : il n'apparaît ni dans la ligne de
commande, ni dans l'historique du shell.

La reconstruction du stock s'appelle de la même façon, une entreprise à la fois :

    python -m app.cli rebuild-stock --company-id <uuid>

Elle sera planifiée en phase 08 ; en attendant, elle s'exécute à la demande.

Le pipeline CoGes Intelligence (phase 09) se lance aussi à la main, pour une
vérification ou un rattrapage — les mêmes étapes que les tâches nocturnes, sous
`coges_analytics`, dans le processus de la commande (jamais dans l'API) :

    python -m app.cli run-intelligence --company-id <uuid> [--as-of 2026-09-24] [--train]

Les comptes de l'équipe CoGes (administration de la plateforme, ADR 0089) naissent ici
aussi, jamais par une route publique ; le mot de passe est demandé de la même façon :

    python -m app.cli create-platform-user --email equipe@example.test \
        --name "Prénom Nom" --role administrator

Téléphone perdu et aucun autre administrateur pour réinitialiser la double
authentification (ADR 0105) : dernier recours sur le serveur.

    python -m app.cli reset-platform-mfa --email equipe@example.test
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT
from app.core.errors import ValidationFailedError
from app.core.tenancy import TenantContext, tenant_transaction
from app.modules.companies import service as companies_service
from app.modules.inventory import service as inventory_service
from app.modules.inventory.schemas import StockRebuildLine
from app.modules.platform import service as platform_service
from app.modules.rbac import service as rbac_service
from app.modules.rbac.matrix import MANAGER
from app.modules.users import service as users_service
from app.modules.users.schemas import UserCreate

MIN_PASSWORD_LENGTH = 12


def _manager_payload(
    *, email: str | None, phone: str | None, full_name: str, password: str | None
) -> UserCreate:
    """Le gérant passe par le schéma de l'écran Personnes : e-mail validé comme à
    l'API, numéro ramené à ses chiffres comme à la connexion, l'un des deux exigé.

    Vérifié avant d'ouvrir la transaction : une identité refusée ne crée rien.
    """
    try:
        return UserCreate(
            email=(email or "").strip() or None,
            phone=phone,
            full_name=full_name,
            password=password,
        )
    except ValidationError as exc:
        error = exc.errors()[0]
        field = error["loc"][0] if error["loc"] else None
        if field == "email":
            raise SystemExit(f"Adresse e-mail invalide : {email}") from exc
        if field == "password":
            raise SystemExit(
                f"Le mot de passe doit faire au moins {MIN_PASSWORD_LENGTH} caractères."
            ) from exc
        raise SystemExit(str(error["msg"]).removeprefix("Value error, ")) from exc


def create_company(
    *,
    name: str,
    slug: str,
    manager_name: str,
    password: str,
    currency: str,
    timezone: str,
    manager_email: str | None = None,
    manager_phone: str | None = None,
) -> tuple[str, str]:
    """Crée l'entreprise, ses rôles système et son gérant. Renvoie (company_id, user_id).

    Le gérant a un e-mail, un téléphone, ou les deux (ADR 0074).
    """
    payload = _manager_payload(
        email=manager_email, phone=manager_phone, full_name=manager_name, password=password
    )

    company_id = uuid4()
    manager_id = uuid4()
    ctx = TenantContext(user_id=manager_id, company_id=company_id)

    try:
        with tenant_transaction(ctx) as session:
            companies_service.create_company(
                session, ctx, name=name, slug=slug, currency=currency, timezone=timezone
            )
            roles = rbac_service.create_system_roles(session, ctx)
            # Même façade que l'écran Personnes : mêmes contrôles d'unicité, mêmes
            # messages. Sans rôle ici : le gérant n'existe pas encore pour déléguer.
            manager, _ = users_service.create_user(session, ctx, payload, user_id=manager_id)
            # L'auteur de l'audit est le gérant lui-même, déjà écrit (flush) en base.
            rbac_service.assign_role(session, ctx, manager.id, roles[MANAGER].id)
    except ValidationFailedError as exc:
        raise SystemExit(exc.message) from exc

    return str(company_id), str(manager_id)


def _prompt_password(label: str = "Mot de passe du gérant : ") -> str:
    password = getpass.getpass(label)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Le mot de passe doit faire au moins {MIN_PASSWORD_LENGTH} caractères.")
    if password != getpass.getpass("Confirmer le mot de passe : "):
        raise SystemExit("Les deux saisies diffèrent.")
    return password


def rebuild_stock(company_id: UUID) -> list[StockRebuildLine]:
    """Rejoue le journal d'une entreprise et réaligne sa projection de stock.

    Une entreprise par transaction : `rebuild_product_stock` s'appuie sur une table
    temporaire `ON COMMIT DROP`, qui interdit deux appels dans la même transaction.
    Le contexte tenant est posé comme partout ailleurs, par `tenant_transaction` :
    la fonction s'exécute sous RLS, sans privilège particulier.
    """
    ctx = TenantContext.bootstrap(company_id)
    with tenant_transaction(ctx) as session:
        return inventory_service.rebuild_stock(session, ctx)


def run_intelligence(company_id: UUID, *, as_of: str | None, retrain: bool) -> list[str]:
    """Étapes 04 à 07 pour une entreprise ; renvoie un compte rendu lisible.

    Importée ici et non en tête : le pipeline tire numpy et statsmodels, dont les
    autres commandes n'ont pas besoin.
    """
    from app.modules.intelligence.pipelines import run_features, run_inference, run_training
    from app.workers.tasks.intelligence_common import artifact_store, run_for_company

    report: list[str] = []

    def _step(session: Session, ctx: TenantContext, day: date) -> None:
        features = run_features(session, ctx, as_of=day)
        if features is None:
            report.append("CoGes Intelligence est désactivée pour cette entreprise.")
            return
        report.append(
            f"as_of {day.isoformat()} : {features.written} photographie(s) écrite(s), "
            f"{features.already_present} déjà présente(s), {features.labelled} label(s)"
        )
        if retrain:
            trained = run_training(session, ctx, as_of=day, store=artifact_store())
            if trained is not None:
                report.append(
                    f"Modèle {trained.model_name} {trained.model_version} : "
                    f"{trained.fitted} produit(s) ajusté(s) → {trained.path}"
                )
        result = run_inference(session, ctx, as_of=day, store=artifact_store())
        if result is not None:
            inferred = result.inferred
            report.append(
                f"{inferred.forecast_rows} prévision(s) pour {inferred.products} produit(s) "
                f"({inferred.seasonal_products} saisonnier, {inferred.baseline_products} "
                f"moyenne mobile), {inferred.insufficient} sous le seuil d'historique"
            )
            report.append(
                f"Insights : {result.insights.emitted}, résolus {result.insights.resolved}, "
                f"notifications {result.insights.notified}"
            )

    run_for_company(str(company_id), as_of, _step)
    return report


#: Contrat versionné : `frontend/types/` en est généré, jamais écrit à la main.
OPENAPI_PATH = REPO_ROOT / "backend" / "openapi.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="Administration de CoGes")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-company", help="Créer une entreprise et son gérant")
    create.add_argument("--name", required=True, help="Raison sociale")
    create.add_argument("--slug", required=True, help="Identifiant de connexion, a-z0-9-")
    create.add_argument("--manager-email", default=None, help="E-mail du gérant")
    create.add_argument(
        "--manager-phone",
        default=None,
        help="Téléphone du gérant, sous toute forme (« 77 123 45 67 », « +221… ») ; "
        "l'e-mail ou le téléphone au moins",
    )
    create.add_argument("--manager-name", required=True)
    create.add_argument("--currency", default="XOF")
    create.add_argument("--timezone", default="Africa/Dakar")
    create.add_argument(
        "--password",
        default=None,
        help="À éviter : le mot de passe resterait dans l'historique du shell.",
    )

    rebuild = subparsers.add_parser(
        "rebuild-stock", help="Recalculer stock et CMP d'une entreprise depuis le journal"
    )
    rebuild.add_argument("--company-id", required=True, type=UUID)

    intelligence = subparsers.add_parser(
        "run-intelligence", help="Features, prévisions et insights d'une entreprise"
    )
    intelligence.add_argument("--company-id", required=True, type=UUID)
    intelligence.add_argument("--as-of", default=None, help="AAAA-MM-JJ ; la veille par défaut")
    intelligence.add_argument(
        "--train", action="store_true", help="Réentraîner le modèle de la semaine d'abord"
    )
    platform_user = subparsers.add_parser(
        "create-platform-user", help="Créer un compte de l'administration de la plateforme"
    )
    platform_user.add_argument("--email", required=True)
    platform_user.add_argument("--name", required=True, help="Nom affiché")
    platform_user.add_argument("--role", required=True, choices=["administrator", "support"])
    platform_user.add_argument(
        "--password",
        default=None,
        help="Parcours e2e seulement : le mot de passe resterait dans l'historique du shell.",
    )
    platform_user.add_argument(
        "--mfa-secret",
        default=None,
        help="Parcours e2e seulement (refusé hors local et ci) : secret TOTP en base32, "
        "double authentification active d'emblée.",
    )

    reset_mfa = subparsers.add_parser(
        "reset-platform-mfa",
        help="Réinitialiser la double authentification d'un compte de l'administration "
        "(sessions fermées, réenrôlement à la connexion suivante)",
    )
    reset_mfa.add_argument("--email", required=True)

    deactivate = subparsers.add_parser(
        "deactivate-platform-user", help="Couper un compte de l'administration (sessions comprises)"
    )
    deactivate.add_argument("--email", required=True)

    openapi = subparsers.add_parser(
        "export-openapi", help="Écrire le contrat OpenAPI versionné (source des types du front)"
    )
    openapi.add_argument("--output", default=str(OPENAPI_PATH), help="Fichier de sortie")
    return parser


def openapi_document() -> str:
    """Contrat OpenAPI de l'API, sérialisé de façon stable (diff lisible en revue)."""
    from app.main import app  # noqa: PLC0415 - n'importe l'API que pour cette commande

    return json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "create-company":
        # Identité vérifiée avant de demander le mot de passe : une faute de frappe
        # ne coûte pas deux saisies.
        manager = _manager_payload(
            email=args.manager_email,
            phone=args.manager_phone,
            full_name=args.manager_name,
            password=None,
        )
        password = args.password or _prompt_password()
        company_id, user_id = create_company(
            name=args.name,
            slug=args.slug,
            manager_email=args.manager_email,
            manager_phone=args.manager_phone,
            manager_name=args.manager_name,
            password=password,
            currency=args.currency,
            timezone=args.timezone,
        )
        print(f"Entreprise créée : {company_id}")
        print(f"Gérant créé      : {user_id}")
        login = f"email={manager.email}" if manager.email else f"téléphone={manager.phone}"
        print(f"Connexion        : slug={args.slug} {login}")

    if args.command == "rebuild-stock":
        gaps = rebuild_stock(args.company_id)
        if not gaps:
            print("Aucun écart : la projection est conforme au journal.")
        for gap in gaps:
            print(
                f"Écart produit {gap.product_id} : "
                f"quantité {gap.qty_ecart:+}, CMP {gap.avg_ecart:+}"
            )

    if args.command == "create-platform-user":
        try:
            platform_user_id = platform_service.create_platform_user(
                email=args.email,
                display_name=args.name,
                role=args.role,
                password=args.password or _prompt_password("Mot de passe du compte : "),
                mfa_secret=args.mfa_secret,
            )
        except platform_service.MfaSecretOutsideDevelopmentError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"Compte d'administration créé : {platform_user_id} ({args.role})")

    if args.command == "reset-platform-mfa":
        if not platform_service.reset_platform_mfa(email=args.email):
            print(f"Aucun compte : {args.email}")
            return 1
        print(
            f"Double authentification réinitialisée, sessions fermées : {args.email}. "
            "Le compte l'enrôlera à sa prochaine connexion."
        )

    if args.command == "deactivate-platform-user":
        if not platform_service.deactivate_platform_user(email=args.email):
            print(f"Aucun compte actif : {args.email}")
            return 1
        print(f"Compte coupé, sessions révoquées : {args.email}")

    if args.command == "export-openapi":
        Path(args.output).write_text(openapi_document(), encoding="utf-8")
        print(f"Contrat OpenAPI écrit : {args.output}")

    if args.command == "run-intelligence":
        for line in run_intelligence(args.company_id, as_of=args.as_of, retrain=args.train):
            print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
