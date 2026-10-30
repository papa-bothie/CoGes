"""Garde-fou 2 de l'ADR 0042 : le contrôle des environnements d'exécution."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "deploy" / "scripts" / "check_runtime_env.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_runtime_env", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_versioned_compose_files_hold_no_owner_dsn() -> None:
    assert _module().main([]) == 0


def test_owner_variable_or_dsn_is_refused() -> None:
    check = _module()
    assert check.violations(
        [
            ("COGES_DATABASE_URL_APP", "postgresql+psycopg://coges_app:x@h/db"),
            ("COGES_DATABASE_URL_OWNER", "postgresql+psycopg://coges_owner:x@h/db"),
            ("DATABASE_URL", "postgres://coges_owner@h/db"),
        ],
        source="test",
    ) == [
        "test : la variable COGES_DATABASE_URL_OWNER ne doit pas exister à l'exécution",
        "test : DATABASE_URL désigne l'utilisateur coges_owner",
    ]


def test_compose_mentioning_the_owner_is_refused(tmp_path: Path) -> None:
    compose = tmp_path / "compose.yml"
    compose.write_text(
        "services:\n  worker:\n    environment:\n"
        "      COGES_DATABASE_URL_OWNER: ${COGES_DATABASE_URL_OWNER}\n",
        encoding="utf-8",
    )
    assert _module().main(["--compose", str(compose)]) == 1


def test_vps_requires_an_env_file() -> None:
    assert _module().main(["--require-vps"]) == 1


_GOOD_ENV = """
# Pile de production (ADR 0083)
COGES_STACK=production
COGES_DOMAIN=app.exemple.sn
COGES_DATABASE_URL_APP=postgresql+psycopg://coges_app:x@ep-1.eu-central-1.aws.neon.tech/coges?sslmode=require
COGES_DATABASE_URL_RELAY=postgresql+psycopg://coges_relay:x@ep-1.eu-central-1.aws.neon.tech/coges?sslmode=require
COGES_DATABASE_URL_ANALYTICS="postgresql+psycopg://coges_analytics:x@ep-1.eu-central-1.aws.neon.tech/coges?sslmode=require"
COGES_DATABASE_URL_PLATFORM=postgresql+psycopg://coges_app_platform:x@ep-1.eu-central-1.aws.neon.tech/coges?sslmode=require
COGES_ADMIN_ALLOWED_IPS="196.207.1.10 2001:db8::/48"
COGES_REDIS_PASSWORD=ci-redis-password-00000000000000000000
COGES_JWT_SECRET=ci-jwt-secret-0000000000000000000000
COGES_MFA_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
"""


def _env(tmp_path: Path, text: str) -> list[str]:
    path = tmp_path / "coges.env"
    path.write_text(text, encoding="utf-8")
    return ["--require-vps", "--env-file", str(path)]


def test_a_complete_vps_env_file_passes(tmp_path: Path) -> None:
    assert _module().main(_env(tmp_path, _GOOD_ENV)) == 0


def test_the_example_env_file_is_refused_until_filled() -> None:
    example = SCRIPT.parents[1] / "vps" / "coges.env.example"
    assert _module().main(["--require-vps", "--env-file", str(example)]) == 1


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (("sslmode=require", "sslmode=disable"), "sslmode=require"),
        (("ep-1.eu-central-1.aws.neon.tech", "localhost"), "base locale"),
        (("COGES_DOMAIN=app.exemple.sn", "COGES_DOMAIN=https://app.exemple.sn"), "nom d'hôte nu"),
        (("COGES_DOMAIN=app.exemple.sn", "COGES_DOMAIN="), "COGES_DOMAIN invalide"),
        (("COGES_JWT_SECRET=ci-jwt-secret-0000000000000000000000", "COGES_JWT_SECRET=court"), "32"),
        (
            ("COGES_STACK=production", "COGES_REDIS_URL=redis://:p@redis.example.com:6379/0"),
            "Redis interne",
        ),
        (
            ("COGES_STACK=production", "COGES_DATABASE_URL_OWNER=postgresql://coges_owner:x@h/db"),
            "COGES_DATABASE_URL_OWNER",
        ),
        (
            ("coges_app:x", "coges_owner:x"),
            "coges_owner",
        ),
        # Administration de la plateforme (ADR 0089).
        (("coges_app_platform:x", "coges_app:x"), "coges_app_platform"),
        (('COGES_ADMIN_ALLOWED_IPS="196.207.1.10 2001:db8::/48"', ""), "ALLOWED_IPS est vide"),
        (("196.207.1.10 2001:db8::/48", "196.207.1.10 bureau"), "« bureau », illisible"),
        (("196.207.1.10 2001:db8::/48", "0.0.0.0/0"), "à tous"),
    ],
)
def test_vps_env_file_rules(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: tuple[str, str], reason: str
) -> None:
    text = _GOOD_ENV.replace(*change)
    assert _module().main(_env(tmp_path, text)) == 1
    assert reason in capsys.readouterr().err


# ---------------------------------------------- contournements de la revue (P2.18, ADR 0088)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        # Le propriétaire Neon, qui n'est pas « coges_owner » mais a tous les droits.
        (("coges_app:x", "neondb_owner:x"), "neondb_owner"),
        # Encodé : « coges%5Fowner » se lit coges_owner une fois décodé.
        (("coges_app:x", "coges%5Fowner:x"), "coges_owner"),
        # Utilisateur passé en paramètre, sans rien avant « @ ».
        (
            (
                "coges_app:x@ep-1.eu-central-1.aws.neon.tech/coges?sslmode=require",
                "ep-1.eu-central-1.aws.neon.tech/coges?sslmode=require&user=coges_owner",
            ),
            "coges_owner",
        ),
        # Le bon rôle au mauvais endroit : le relais sous coges_app.
        (("coges_relay:x", "coges_app:x"), "coges_relay"),
    ],
)
def test_vps_dsn_users_are_an_allow_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: tuple[str, str], reason: str
) -> None:
    text = _GOOD_ENV.replace(*change, 1)
    assert _module().main(_env(tmp_path, text)) == 1
    assert reason in capsys.readouterr().err


def test_an_encoded_owner_in_a_compose_file_is_refused(tmp_path: Path) -> None:
    compose = tmp_path / "compose.yml"
    compose.write_text(
        "environment:\n  COGES_DATABASE_URL_APP: postgresql://coges%5Fowner:x@h/db\n",
        encoding="utf-8",
    )
    assert _module().main(["--compose", str(compose)]) == 1


def test_the_stack_of_the_env_file_must_match(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Une préproduction copiée du modèle de production ne prend jamais ses alias."""
    assert _module().main([*_env(tmp_path, _GOOD_ENV), "--stack", "preprod"]) == 1
    assert "COGES_STACK" in capsys.readouterr().err
    assert _module().main([*_env(tmp_path, _GOOD_ENV), "--stack", "production"]) == 0


def test_the_preprod_stack_needs_no_admin_allow_list(tmp_path: Path) -> None:
    """Seule la production sert l'administration (ADR 0089)."""
    text = _GOOD_ENV.replace("COGES_STACK=production", "COGES_STACK=preprod").replace(
        'COGES_ADMIN_ALLOWED_IPS="196.207.1.10 2001:db8::/48"', ""
    )
    assert _module().main([*_env(tmp_path, text), "--stack", "preprod"]) == 0


# ------------------------------------------- porte de l'administration (ADR 0104)

_TEAM = "coges.cloudflareaccess.com"
_AUD = "a" * 64
_TUNNEL = "t" * 120
_CLOUDFLARE_ENV = _GOOD_ENV.replace(
    'COGES_ADMIN_ALLOWED_IPS="196.207.1.10 2001:db8::/48"',
    f"COGES_ADMIN_GATE=cloudflare\nCOGES_ADMIN_ALLOWED_IPS=\nCOGES_ACCESS_TEAM_DOMAIN={_TEAM}\n"
    f"COGES_ACCESS_AUD={_AUD}\nCOGES_CLOUDFLARE_TUNNEL_TOKEN={_TUNNEL}",
)


def test_without_a_gate_the_admin_stays_behind_its_ip_list(tmp_path: Path) -> None:
    """Un fichier d'avant ce lot (sans `COGES_ADMIN_GATE`) se lit comme le mode `ip`."""
    assert "COGES_ADMIN_GATE" not in _GOOD_ENV
    assert _module().main(_env(tmp_path, _GOOD_ENV)) == 0


@pytest.mark.parametrize(
    "text",
    [
        _CLOUDFLARE_ENV,
        # Filet facultatif : des adresses en plus de Cloudflare Access.
        _CLOUDFLARE_ENV.replace("COGES_ADMIN_ALLOWED_IPS=", "COGES_ADMIN_ALLOWED_IPS=196.207.1.10"),
        _GOOD_ENV.replace("COGES_STACK=production", "COGES_STACK=production\nCOGES_ADMIN_GATE=ip"),
        # Secours par SSH : ni adresses ni Access.
        _GOOD_ENV.replace("COGES_STACK=production", "COGES_ADMIN_GATE=ssh").replace(
            'COGES_ADMIN_ALLOWED_IPS="196.207.1.10 2001:db8::/48"', ""
        ),
    ],
    ids=["cloudflare", "cloudflare+ip", "ip", "ssh"],
)
def test_the_admin_gates_that_pass(tmp_path: Path, text: str) -> None:
    assert _module().main(_env(tmp_path, text)) == 0


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        (_CLOUDFLARE_ENV.replace("=cloudflare", "=ouvert"), "COGES_ADMIN_GATE vaut « ouvert »"),
        (_CLOUDFLARE_ENV.replace("=cloudflare", "="), "COGES_ADMIN_GATE vaut «  »"),
        (
            _CLOUDFLARE_ENV.replace(
                f"COGES_ACCESS_TEAM_DOMAIN={_TEAM}", "COGES_ACCESS_TEAM_DOMAIN="
            ),
            "COGES_ACCESS_TEAM_DOMAIN",
        ),
        (
            _CLOUDFLARE_ENV.replace(_TEAM, "https://coges.cloudflareaccess.com"),
            "COGES_ACCESS_TEAM_DOMAIN",
        ),
        (_CLOUDFLARE_ENV.replace(_TEAM, "coges.example.com"), "COGES_ACCESS_TEAM_DOMAIN"),
        (_CLOUDFLARE_ENV.replace(_AUD, "abc"), "COGES_ACCESS_AUD"),
        (_CLOUDFLARE_ENV.replace(_AUD, ""), "COGES_ACCESS_AUD"),
        (_CLOUDFLARE_ENV.replace(_TUNNEL, ""), "COGES_CLOUDFLARE_TUNNEL_TOKEN"),
        (_CLOUDFLARE_ENV.replace(_TUNNEL, "court"), "COGES_CLOUDFLARE_TUNNEL_TOKEN"),
        (
            _CLOUDFLARE_ENV.replace(
                "COGES_ADMIN_ALLOWED_IPS=", "COGES_ADMIN_ALLOWED_IPS=0.0.0.0/0"
            ),
            "à tous",
        ),
        # Retour arrière à moitié fait : l'API exigerait un jeton qui n'arrive plus.
        (
            _CLOUDFLARE_ENV.replace("=cloudflare", "=ip").replace(
                "COGES_ADMIN_ALLOWED_IPS=", "COGES_ADMIN_ALLOWED_IPS=196.207.1.10"
            ),
            "videz COGES_ACCESS_TEAM_DOMAIN",
        ),
        (_CLOUDFLARE_ENV.replace("=cloudflare", "=ssh"), "videz COGES_ACCESS_TEAM_DOMAIN"),
        (
            _GOOD_ENV.replace("COGES_STACK=production", "COGES_ADMIN_GATE=ip").replace(
                'COGES_ADMIN_ALLOWED_IPS="196.207.1.10 2001:db8::/48"', ""
            ),
            "ALLOWED_IPS est vide",
        ),
    ],
    ids=lambda value: value if len(value) < 60 else "",
)
def test_the_admin_gates_that_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, reason: str
) -> None:
    assert _module().main(_env(tmp_path, text)) == 1
    assert reason in capsys.readouterr().err


# ------------------------------- double authentification de l'administration (ADR 0105)

_MFA_ENV = _GOOD_ENV.replace(
    'COGES_ADMIN_ALLOWED_IPS="196.207.1.10 2001:db8::/48"', "COGES_ADMIN_GATE=mfa"
)


def test_the_mfa_gate_needs_no_address_list(tmp_path: Path) -> None:
    assert "COGES_ADMIN_ALLOWED_IPS" not in _MFA_ENV
    assert _module().main(_env(tmp_path, _MFA_ENV)) == 0


@pytest.mark.parametrize("text", [_GOOD_ENV, _MFA_ENV, _CLOUDFLARE_ENV])
@pytest.mark.parametrize(
    ("key", "reason"),
    [
        ("", "COGES_MFA_ENCRYPTION_KEY est vide"),
        ("trop-courte", "32 octets en base64url"),
        ("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "32 octets en base64url"),
    ],
)
def test_every_gate_needs_the_mfa_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, key: str, reason: str
) -> None:
    """L'API refuse de démarrer sans elle : la refuser avant de toucher à la pile."""
    broken = text.replace(
        "COGES_MFA_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        f"COGES_MFA_ENCRYPTION_KEY={key}",
    )
    assert _module().main(_env(tmp_path, broken)) == 1
    assert reason in capsys.readouterr().err


def test_the_preprod_stack_needs_the_mfa_key_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = _GOOD_ENV.replace("COGES_STACK=production", "COGES_STACK=preprod").replace(
        "COGES_MFA_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n", ""
    )
    assert _module().main([*_env(tmp_path, text), "--stack", "preprod"]) == 1
    assert "COGES_MFA_ENCRYPTION_KEY" in capsys.readouterr().err


def test_the_mfa_gate_needs_a_version_that_imposes_mfa(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Le contrôle lit une constante du code, pas une variable : un bundle qui
    n'imposerait pas le code ne peut pas ouvrir l'administration sans filtre."""
    check = _module()
    check.PLATFORM_MFA_REQUIRED = False
    assert check.main(_env(tmp_path, _MFA_ENV)) == 1
    assert "impose la double authentification" in capsys.readouterr().err
    # Les autres portes gardent leur protection propre.
    assert check.main(_env(tmp_path, _GOOD_ENV)) == 0


def test_the_mfa_gate_refuses_leftover_access_variables(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = _MFA_ENV + f"COGES_ACCESS_TEAM_DOMAIN={_TEAM}\nCOGES_ACCESS_AUD={_AUD}\n"
    assert _module().main(_env(tmp_path, text)) == 1
    assert "videz COGES_ACCESS_TEAM_DOMAIN" in capsys.readouterr().err


def test_the_script_and_the_api_agree_that_mfa_is_required() -> None:
    from app.core import mfa  # noqa: PLC0415

    assert _module().PLATFORM_MFA_REQUIRED is mfa.PLATFORM_MFA_REQUIRED is True
