"""`LEGAL_VERSION` suit les textes du front (prompt 36, ADR 0117).

Republier un texte, c'est changer sa ligne `<!-- version: AAAA-MM-JJ -->` **et** la
constante : sans quoi personne ne serait invité à relire. Ce test refuse l'oubli.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from app.core.legal import LEGAL_VERSION

LEGAL_DIR = Path(__file__).resolve().parents[3] / "frontend" / "content" / "legal"
TEXTS = ("conditions.md", "confidentialite.md")
VERSION_LINE = re.compile(r"\A<!-- version: (\d{4}-\d{2}-\d{2}) -->\n")


def _version(name: str) -> str:
    content = (LEGAL_DIR / name).read_text(encoding="utf-8")
    match = VERSION_LINE.match(content)
    assert match, f"{name} doit commencer par <!-- version: AAAA-MM-JJ -->"
    date.fromisoformat(match.group(1))
    return match.group(1)


def test_legal_version_is_the_latest_of_both_texts() -> None:
    assert max(_version(name) for name in TEXTS) == LEGAL_VERSION


def test_no_placeholder_is_left_in_the_texts() -> None:
    for name in TEXTS:
        content = (LEGAL_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"\[(à définir|à confirmer|date)[^\]]*\]", content, re.I), name
