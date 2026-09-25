"""Schémas du module System."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OutboxHealth(BaseModel):
    """État de l'outbox pour l'entreprise du contexte.

    Les trois compteurs se lisent ensemble : `pending` qui monte sans que `published`
    bouge signale un relais arrêté ; `dead_lettered` non nul signale des événements
    qu'aucune reprise ne rattrapera plus.
    """

    model_config = ConfigDict(extra="forbid")

    #: Événements écrits, pas encore publiés, et encore réclamables.
    pending: int
    #: Événements ayant épuisé leurs dix tentatives : plus aucune reprise automatique.
    dead_lettered: int
    #: Événements publiés depuis toujours — repère, pas une alerte.
    published: int
    #: Date du plus ancien événement en attente : c'est elle qui dit si le retard
    #: se compte en secondes ou en jours.
    oldest_pending_at: datetime | None
    #: Dernière publication observée.
    last_published_at: datetime | None
