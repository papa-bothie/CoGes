"""Le numéro WhatsApp du support est le même pour l'API et la vitrine (ADR 0118)."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import Settings

VITRINE = Path(__file__).resolve().parents[3] / "frontend" / "content" / "vitrine.ts"


def test_the_api_default_is_the_landing_page_number() -> None:
    match = re.search(r'whatsappNumber:\s*"(\d+)"', VITRINE.read_text(encoding="utf-8"))
    assert match, "whatsappNumber introuvable dans content/vitrine.ts"
    assert Settings.model_fields["support_whatsapp"].default == match.group(1)
