"""Support à distance sur site (ADR 0129) : la liste fermée de ce qui sort du PC.

Les tests de comportement sont en Pester (deploy/onprem/windows/tests/CoGes.Support.Tests.ps1)
et dans `deploy/onprem-ci/verifier.sh` ; ici : la liste elle-même, et qu'elle est la même
partout où elle est écrite (script, CI, ADR, annexe du contrat).
"""

from __future__ import annotations

import importlib.util
import re
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[3]
ONPREM = REPO / "deploy" / "onprem"
FIELDS = ONPREM / "support" / "champs.txt"
ADR = REPO / "docs" / "decisions" / "0129-support-a-distance-sur-site.md"
ANNEX = REPO / "docs" / "contrat" / "annexe-donnees-sur-site.md"
SCRIPT = ONPREM / "windows" / "CoGes.Install.ps1"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


controle = _load(REPO / "deploy" / "onprem-ci" / "controle_remontee.py", "onprem_controle_remontee")
NAMES = [name for name, _ in controle.load_fields(FIELDS)]

#: Un corps valide : le résumé minimal du script, pour un PC qui va bien.
GOOD = {
    "format": "COGES-RESUME-1",
    "pc": "0123456789abcdef" * 2,
    "signal": "sauvegarde",
    "resultat": "echec",
    "raison": "place-disque",
    "envoye_le": "2026-11-22T13:00",
    "version": "v0.4.1",
    "canal": "stable",
    "maj": "reussie",
    "maj_le": "2026-11-20T21:34",
    "maj_attente": "aucune",
    "services_ok": "8/9",
    "services_ko": "beat",
    "licence": "active",
    "offre": "starter",
    "sauvegarde_le": "2026-11-22T13:00",
    "copie_le": "jamais",
    "essai": "ok",
    "essai_le": "2026-11-16T13:02",
    "disque_go": "41.3",
    "memoire_go": "7.8",
    "windows": "10.0.26100",
    "docker": "4.37.1",
    "wsl": "2.3.26.0",
    "erreurs_24h": "sauvegarde=2",
}


def _body(values: dict[str, str]) -> str:
    return "".join(f"{name}: {value}\n" for name, value in values.items())


def test_the_list_is_closed_and_compiles() -> None:
    assert list(GOOD) == NAMES
    assert len(NAMES) == len(set(NAMES)) == 25
    for _name, rule in controle.load_fields(FIELDS):
        assert rule.pattern.startswith("^(?:") and rule.pattern.endswith(")$")


def test_a_good_body_passes_and_stays_under_two_kilobytes() -> None:
    values = controle.check_body(_body(GOOD), controle.load_fields(FIELDS))
    assert values["raison"] == "place-disque"
    assert len(_body(GOOD).encode()) < 2048


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"chiffre_affaires": "125000"}, "hors de la liste"),
        ({"raison": "base inaccessible : Awa Diop"}, "hors de sa règle"),
        ({"pc": "keur-fatou"}, "hors de sa règle"),
        ({"services_ko": "api,client-x"}, "hors de sa règle"),
        ({"offre": "starter (note : remise 20 %)"}, "hors de sa règle"),
        ({"version": "v1.2.3 Keur Fatou"}, "hors de sa règle"),
    ],
)
def test_any_field_outside_the_list_or_its_rule_is_refused(
    change: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        controle.check_body(_body({**GOOD, **change}), controle.load_fields(FIELDS))


def test_a_missing_field_is_refused() -> None:
    values = dict(GOOD)
    del values["licence"]
    with pytest.raises(ValueError, match="au lieu de"):
        controle.check_body(_body(values), controle.load_fields(FIELDS))


def test_no_rule_lets_free_text_through() -> None:
    """Aucune règle n'accepte une phrase : une valeur porte au plus des chiffres, des
    lettres minuscules, des points, des virgules, des tirets et « depuis N j »."""
    fields = controle.load_fields(FIELDS)
    for sentence in ("Awa Diop", "Riz brisé 25 kg", "77 123 45 67", "postgresql://x:y@z"):
        for name, rule in fields:
            assert not rule.match(sentence), (name, sentence)


def test_the_adr_and_the_contract_annex_list_exactly_the_same_fields() -> None:
    for document in (ADR, ANNEX):
        text = document.read_text(encoding="utf-8")
        listed = re.findall(r"^\| `([a-z_0-9-]+)` \|", text, flags=re.MULTILINE)
        assert listed == NAMES, document.name


def test_the_script_checks_every_report_against_the_same_list() -> None:
    """Get-CogesMinimalFact remplit des valeurs par défaut, mais rien ne part sans passer par
    Get-CogesReport, qui refuse tout ce que champs.txt ne nomme pas (Pester le prouve)."""
    code = SCRIPT.read_text(encoding="utf-8-sig")
    assert "support\\champs.txt" in code
    start = code.index("function Send-CogesPing")
    send = code[start : code.index("function Invoke-CogesTestSupport")]
    assert send.count("Format-CogesReport (Get-CogesReport -Facts") == 2


def test_the_ping_never_listens_and_never_obeys() -> None:
    code = SCRIPT.read_text(encoding="utf-8-sig")
    for forbidden in ("HttpListener", "TcpListener", "New-NetFirewallRule", "Invoke-Expression"):
        assert forbidden not in code
    # Une seule fonction parle à Internet pour le support, en POST, et ne lit pas la réponse.
    start = code.index("function Invoke-CogesPingRequest")
    body = code[start : code.index("function Send-CogesPing")]
    assert "-Method Post" in body
    assert "StatusCode" in body and "Content" not in body.replace("ContentType", "")


def test_the_license_command_returns_numbers_and_plan_codes_only() -> None:
    base = (ONPREM / "sauvegarde" / "base.py").read_text(encoding="utf-8")
    start = base.index("def cmd_license")
    body = base[start : base.index("\n\n\n", start)]
    sql = re.findall(r'"(SELECT [^"]*|FROM [^"]*)"', body)
    assert sql == [
        "SELECT to_regclass('public.subscriptions')",
        "SELECT s.status::text, p.code, s.current_period_end IS NULL ",
        "FROM subscriptions s JOIN plans p ON p.id = s.plan_id",
    ]


def test_the_check_tool_finds_a_secret_or_a_demo_name_in_a_zip(tmp_path: Path) -> None:
    env = tmp_path / "coges.env"
    env.write_text(
        "COGES_APP_PASSWORD=" + "ab" * 16 + "\nCOGES_PUBLIC_URL=http://localhost:8080\n",
        encoding="utf-8",
    )
    good = tmp_path / "bon.zip"
    with zipfile.ZipFile(good, "w") as archive:
        for name in ("etat.txt", "resume.txt", "docker.txt", "reglages.txt", "sauvegardes.txt"):
            # L'adresse de CoGes n'est pas un secret : Etat la montre.
            archive.writestr(name, "COGES_APP_PASSWORD\n********\nhttp://localhost:8080\n")
    assert controle.check_zip(good, env, ["Riz brisé"]) == 0
    bad = tmp_path / "mauvais.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("etat.txt", "mot de passe " + "ab" * 16)
        archive.writestr("services/api.log", "vente de Riz brisé")
    assert controle.check_zip(bad, env, ["Riz brisé"]) == 1


def test_every_service_log_is_capped() -> None:
    """Bloc E : les journaux Docker de tous les services, outils des lots 4 et 5 compris,
    sont plafonnés (10 Mo × 3) ; aucun service sans `logging`."""
    compose = (ONPREM / "docker-compose.yml").read_text(encoding="utf-8")
    services = compose.split("\nservices:\n", 1)[1].split("\nnetworks:\n", 1)[0]
    blocks = re.split(r"\n  (?=[a-z][a-z-]*:\n)", "\n" + services)
    names = []
    for block in blocks:
        match = re.match(r"([a-z][a-z-]*):\n", block.strip("\n") + "\n")
        if not match:
            continue
        names.append(match.group(1))
        assert "logging: *logging" in block or "<<: *service" in block, match.group(1)
    assert len(names) == 13
    assert 'max-size: "10m", max-file: "3"' in compose
