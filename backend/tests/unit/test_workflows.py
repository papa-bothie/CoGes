"""Workflows GitHub : droits minimaux, actions figées, secrets réservés à main (P2.20).

* `ci.yml` n'avait pas de bloc `permissions` : il héritait des droits par défaut du
  dépôt, parfois en écriture.
* Une action tierce citée par étiquette (`@v6`) suit ce que son éditeur y pousse : une
  étiquette déplacée exécute un autre code avec nos secrets. Figée par condensat, elle
  ne bouge plus.
* Un job qui lit un secret de déploiement ou de sauvegarde ne doit tourner que depuis
  `main` ou une étiquette de version, jamais depuis une branche quelconque lancée à la
  main (les protections d'environnement GitHub, réglées par le propriétaire, doublent
  ce contrôle).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"
#: Les actions de GitHub lui-même restent citées par version majeure.
FIRST_PARTY = ("actions/", "./")
PINNED = re.compile(r"^[^@]+@[0-9a-f]{40}$")
MAIN_OR_TAG = (
    "github.ref == 'refs/heads/main'",
    "startsWith(github.ref, 'refs/tags/v')",
)


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return data


def _uses(node: Any) -> list[str]:
    if isinstance(node, dict):
        found = [node["uses"]] if isinstance(node.get("uses"), str) else []
        return found + [use for value in node.values() for use in _uses(value)]
    if isinstance(node, list):
        return [use for item in node for use in _uses(item)]
    return []


def test_ci_declares_read_only_permissions() -> None:
    assert _load("ci.yml").get("permissions") == {"contents": "read"}


@pytest.mark.parametrize("workflow", sorted(path.name for path in WORKFLOWS.glob("*.yml")))
def test_third_party_actions_are_pinned_by_sha(workflow: str) -> None:
    loose = [
        use
        for use in _uses(_load(workflow))
        if not use.startswith(FIRST_PARTY) and not PINNED.match(use)
    ]
    assert loose == [], f"actions tierces non figées par condensat : {loose}"


@pytest.mark.parametrize(
    ("workflow", "job"),
    [
        ("backup.yml", "backup"),
        ("backup-purge.yml", "purge"),
        ("deploy.yml", "migrate"),
        ("deploy.yml", "deploy"),
    ],
)
def test_jobs_with_secrets_run_only_from_main_or_a_tag(workflow: str, job: str) -> None:
    condition = str(_load(workflow)["jobs"][job].get("if", ""))
    assert all(part in condition for part in MAIN_OR_TAG), (
        f"{workflow} / {job} lit des secrets depuis n'importe quelle branche : « {condition} »"
    )
