"""Script d'installation Windows (ADR 0126) : ce que les fichiers livrés garantissent.

Les tests de comportement sont en Pester (deploy/onprem/windows/tests), joués par le
workflow « Sur site » sous Linux et sous Windows. Ici, la forme des fichiers, vérifiée dans
la CI principale aussi.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
WINDOWS = REPO / "deploy" / "onprem" / "windows"
SCRIPTS = sorted(WINDOWS.rglob("*.ps1"))
#: Le code livré, sans les tests.
SHIPPED = [path for path in SCRIPTS if "tests" not in path.parts]
WORKFLOW = REPO / ".github" / "workflows" / "onprem.yml"


def test_the_expected_scripts_are_there() -> None:
    names = {path.relative_to(WINDOWS).as_posix() for path in SCRIPTS}
    assert names == {
        "installer.ps1",
        "CoGes.Install.ps1",
        "demarrage.ps1",
        "sauvegarde.ps1",
        "mise-a-jour.ps1",
        "tests/CoGes.Install.Tests.ps1",
        "tests/CoGes.Backup.Tests.ps1",
        "tests/CoGes.Update.Tests.ps1",
    }


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda path: path.name)
def test_every_script_is_utf8_with_bom_and_lf(path: Path) -> None:
    """Sans BOM, Windows PowerShell 5.1 lit les accents de travers ; en CRLF, le dossier
    ne serait plus celui que .gitattributes impose."""
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), f"{path.name} : BOM UTF-8 absent"
    assert b"\r" not in raw, f"{path.name} : retour chariot"
    raw[3:].decode("utf-8")


@pytest.mark.parametrize("path", SHIPPED, ids=lambda path: path.name)
def test_no_secret_ever_reaches_a_transcript_or_a_command_line(path: Path) -> None:
    code = path.read_text(encoding="utf-8-sig")
    assert "Start-Transcript" not in code  # enregistrerait ce que le technicien tape
    assert "Invoke-Expression" not in code and "| iex" not in code
    assert "Get-Random" not in code  # secrets : RandomNumberGenerator seulement
    assert "--password" not in code  # create-company demande le mot de passe elle-même (getpass)
    if path.name == "CoGes.Install.ps1":
        # Saisie sans écho impossible : getpass s'arrête au lieu de lire en clair.
        assert "PYTHONWARNINGS=error::getpass.GetPassWarning" in code


def test_settings_are_written_without_bom() -> None:
    """Le piège de `Set-Content -Encoding UTF8` en 5.1 : un BOM casserait la première ligne
    de coges.env."""
    code = (WINDOWS / "CoGes.Install.ps1").read_text(encoding="utf-8-sig")
    assert not re.search(r"(Set|Add|Out)-Content[^\n]*-Encoding\s+UTF8", code)
    assert "New-Object Text.UTF8Encoding $false" in code


def test_docker_is_called_by_one_function_only() -> None:
    code = (WINDOWS / "CoGes.Install.ps1").read_text(encoding="utf-8-sig")
    calls = re.findall(r"(?m)^(?!\s*#).*?(?:&\s*docker\b|-FilePath 'docker')", code)
    # Invoke-Docker : console passée, sortie lue, ou sortie lue avec un texte sur l'entrée
    # standard (la clé privée de la restauration, ADR 0127 : jamais un argument).
    assert len(calls) == 3, calls
    assert sum("$InputText | & docker" in call for call in calls) == 1
    # Jamais « down -v » : les volumes ne s'effacent que par -EffacerLesDonnees.
    assert not re.search(r"'down'[^)\n]*'-v'", code)


def test_the_workflow_runs_pester_on_linux_and_on_windows_powershell() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"(?m)^  onprem-powershell:$", workflow)
    assert re.search(r"(?m)^  onprem-windows:$", workflow)
    assert "runs-on: windows-latest" in workflow
    assert "shell: powershell" in workflow  # Windows PowerShell 5.1
    assert "Invoke-ScriptAnalyzer" in workflow


def test_the_private_key_never_goes_through_an_argument_or_the_environment() -> None:
    """Restauration (ADR 0127) : la clé privée passe par l'entrée standard du conteneur,
    jamais par `-e` (visible par `docker inspect`), ni par un fichier copié sur le PC."""
    code = (WINDOWS / "CoGes.Install.ps1").read_text(encoding="utf-8-sig")
    restore = code[
        code.index("function Restore-CogesBackup") : code.index(
            "function Invoke-CogesCleanOldDatabase"
        )
    ]
    assert "-InputText $key" in restore
    assert "'-e'" not in restore and "COGES_CLE" not in restore
    tool = code[
        code.index("function Get-CogesToolArgument") : code.index("function Invoke-CogesTool ")
    ]
    assert "'-e'" not in tool
    assert "Set-Clipboard" not in code and "clip.exe" not in code
