"""Journalisation structurée en JSON.

Chaque ligne porte `request_id` et `company_id` quand ils sont connus. Aucun secret,
aucun mot de passe, aucun jeton ne transite par les logs.
"""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
company_id_var: ContextVar[str | None] = ContextVar("company_id", default=None)

# Attributs internes de logging.LogRecord : tout le reste est considéré comme contexte métier.
_RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()) | {
    "asctime",
    "message",
    "taskName",
}


#: Ce qu'un message d'erreur ne doit jamais emporter (ADR 0088) : le détail d'une
#: violation d'unicité (« Key (email)=(awa@…) »), une adresse e-mail, un hachage Argon2.
_SCRUBBERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(Key \([^)]*\)=)\([^\n]*?\)( already exists| is not present|\.|$)"), r"\1(…)\2"),
    (re.compile(r"\$argon2[a-z]*\$[^\s'\",)]+"), "[hachage masqué]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[e-mail masqué]"),
)


def scrub_text(value: str) -> str:
    """Le même texte, sans valeur personnelle ni secret reconnaissable."""
    for pattern, replacement in _SCRUBBERS:
        value = pattern.sub(replacement, value)
    return value


class JsonFormatter(logging.Formatter):
    """Formate un enregistrement en une ligne JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": scrub_text(record.getMessage()),
        }

        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        company_id = company_id_var.get()
        if company_id:
            payload["company_id"] = company_id

        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = scrub_text(self.formatException(record.exc_info))

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Installe le formateur JSON sur la racine, une seule fois."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
