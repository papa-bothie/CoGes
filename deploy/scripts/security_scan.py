#!/usr/bin/env python3
"""Analyses de sécurité du dépôt (ADR 0080) : secrets, dépendances Python, dépendances du front.

    python3 deploy/scripts/security_scan.py [all|secrets|python|node]

* **secrets** — gitleaks, version figée, binaire officiel vérifié par SHA-256, sur **tout**
  l'historique git (`.gitleaks.toml`). Valeurs masquées dans la sortie.
* **python** — pip-audit, version figée, sur l'export uv des groupes de production et
  `ml` (le worker). Toute faille connue fait échouer : les avis PyPI n'ont pas toujours
  de gravité, on ne trie pas ce qu'on ne peut pas mesurer.
* **node** — `pnpm audit --prod` ; une faille haute ou critique fait échouer.

Les exceptions vivent dans `security/audit-exceptions.toml` (identifiant, outil, raison,
date de fin) ; une exception échue fait échouer l'analyse. Aucun service payant, aucun
compte : les trois outils sont libres et tournent hors ligne, sauf leurs bases d'avis.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXCEPTIONS_FILE = ROOT / "security" / "audit-exceptions.toml"

GITLEAKS_VERSION = "8.30.1"
#: Sommes publiées par le projet (`gitleaks_8.30.1_checksums.txt`).
GITLEAKS_SHA256 = {
    ("linux", "x64"): "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
    ("linux", "arm64"): "e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080",
    ("darwin", "x64"): "dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709",
    ("darwin", "arm64"): "b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5",
}
PIP_AUDIT_VERSION = "2.10.1"
FAILING_NODE_SEVERITIES = frozenset({"high", "critical"})
TOOLS = frozenset({"pip-audit", "pnpm-audit"})


def _say(message: str) -> None:
    print(f"[security] {message}", flush=True)


# ------------------------------------------------------------------------- exceptions


def load_exceptions(tool: str, today: date | None = None) -> set[str]:
    """Identifiants excusés pour `tool` ; une exception mal formée ou échue fait échouer."""
    if not EXCEPTIONS_FILE.exists():
        return set()
    today = today or date.today()
    entries = tomllib.loads(EXCEPTIONS_FILE.read_text(encoding="utf-8")).get("exception", [])
    excused: set[str] = set()
    problems: list[str] = []
    for entry in entries:
        missing = {"id", "tool", "reason", "until"} - set(entry)
        if missing or entry.get("tool") not in TOOLS or not str(entry.get("reason", "")).strip():
            problems.append(f"exception mal formée : {entry}")
            continue
        if not isinstance(entry["until"], date) or entry["until"] < today:
            problems.append(f"exception échue le {entry['until']} : {entry['id']}")
            continue
        if entry["tool"] == tool:
            excused.add(str(entry["id"]))
    if problems:
        raise SystemExit("\n".join(f"[security] {p}" for p in problems))
    return excused


# --------------------------------------------------------------------------- secrets


def _platform() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    if (system, arch) not in GITLEAKS_SHA256:
        raise SystemExit(f"[security] plate-forme non prise en charge : {system}/{machine}")
    return system, str(arch)


def gitleaks_binary() -> Path:
    """Télécharge gitleaks une fois (cache), après vérification de sa somme SHA-256."""
    system, arch = _platform()
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    target = cache / "coges" / f"gitleaks-{GITLEAKS_VERSION}" / "gitleaks"
    if target.exists():
        return target
    name = f"gitleaks_{GITLEAKS_VERSION}_{system}_{arch}.tar.gz"
    url = f"https://github.com/gitleaks/gitleaks/releases/download/v{GITLEAKS_VERSION}/{name}"
    _say(f"téléchargement de {name}")
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / name
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - URL figée
            archive.write_bytes(response.read())
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != GITLEAKS_SHA256[(system, arch)]:
            raise SystemExit(f"[security] somme SHA-256 inattendue pour {name} : {digest}")
        with tarfile.open(archive) as bundle:
            member = bundle.getmember("gitleaks")
            extracted = bundle.extractfile(member)
            assert extracted is not None  # noqa: S101 - membre régulier
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(extracted.read())
    target.chmod(0o755)
    return target


def scan_secrets() -> bool:
    _say("secrets : gitleaks sur tout l'historique")
    result = subprocess.run(  # noqa: S603 - binaire vérifié, arguments fixes
        [
            str(gitleaks_binary()),
            "git",
            "--config",
            str(ROOT / ".gitleaks.toml"),
            "--redact",
            "--no-banner",
            "--exit-code",
            "1",
            str(ROOT),
        ],
        check=False,
    )
    if result.returncode != 0:
        _say("SECRET TROUVÉ : ne réécrivez pas l'historique, changez d'abord le secret.")
    return result.returncode == 0


# --------------------------------------------------------------------- dépendances


def scan_python() -> bool:
    _say("dépendances Python : pip-audit (production + ml)")
    excused = load_exceptions("pip-audit")
    with tempfile.TemporaryDirectory() as tmp:
        requirements = Path(tmp) / "requirements.txt"
        exported = subprocess.run(  # noqa: S603, S607
            [
                "uv",
                "export",
                "--directory",
                str(ROOT / "backend"),
                "--frozen",
                "--no-dev",
                "--group",
                "ml",
                "--no-hashes",
                "--no-emit-project",
                "--quiet",
                "--output-file",
                str(requirements),
            ],
            check=False,
        )
        if exported.returncode != 0:
            return False
        command = [
            "uvx",
            "--from",
            f"pip-audit=={PIP_AUDIT_VERSION}",
            "pip-audit",
            "-r",
            str(requirements),
            "--no-deps",
            "--disable-pip",
            "--progress-spinner",
            "off",
        ]
        for vuln_id in sorted(excused):
            command += ["--ignore-vuln", vuln_id]
        return subprocess.run(command, check=False).returncode == 0  # noqa: S603


def failing_node_advisories(report: dict[str, object], excused: set[str]) -> list[str]:
    """Avis hauts ou critiques du rapport `pnpm audit --json`, hors exceptions."""
    failing: list[str] = []
    advisories = report.get("advisories", {})
    assert isinstance(advisories, dict)  # noqa: S101
    for advisory in advisories.values():
        ids = {str(advisory.get("github_advisory_id", "")), *map(str, advisory.get("cves", []))}
        if advisory.get("severity") not in FAILING_NODE_SEVERITIES or ids & excused:
            continue
        failing.append(
            f"{advisory.get('severity')} {advisory.get('module_name')} "
            f"{advisory.get('vulnerable_versions')} {advisory.get('github_advisory_id')} "
            f"{advisory.get('title')}"
        )
    return failing


def scan_node() -> bool:
    _say("dépendances du front : pnpm audit --prod (haute ou critique)")
    excused = load_exceptions("pnpm-audit")
    pnpm = shutil.which("pnpm") or "pnpm"
    result = subprocess.run(  # noqa: S603
        [pnpm, "--dir", str(ROOT / "frontend"), "audit", "--prod", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        _say(f"rapport pnpm illisible :\n{result.stdout}\n{result.stderr}")
        return False
    failing = failing_node_advisories(report, excused)
    for line in failing:
        _say(line)
    return not failing


def main(argv: list[str]) -> int:
    which = argv[1] if len(argv) > 1 else "all"
    scans = {"secrets": scan_secrets, "python": scan_python, "node": scan_node}
    if which != "all" and which not in scans:
        raise SystemExit(__doc__)
    selected = scans.values() if which == "all" else [scans[which]]
    results = [scan() for scan in selected]
    _say("tout est propre" if all(results) else "ÉCHEC : voir ci-dessus")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
