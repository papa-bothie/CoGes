"""Planification des batchs — « où s'exécute quoi » de l'Architecture technique.

Toutes les heures sont en **UTC** (`enable_utc = True`). Les entreprises visées sont
ouest-africaines, à l'heure d'UTC ou d'UTC+1 : les créneaux ci-dessous tombent donc
bien hors heures ouvrées, comme l'exige le § 5.7 du Modèle de données.

Chaque tâche planifiée est un **éventail** : elle demande la liste des entreprises à
`active_company_ids()` et enfile une tâche par entreprise, chacune ouvrant sa propre
transaction avec son propre contexte tenant (Diagramme 8). Aucune tâche ne traite
plusieurs entreprises dans une même transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from celery.schedules import crontab

#: Noms des éventails planifiés. Ils vivent ici pour que la planification se lise
#: sans ouvrir les modules de tâches.
REBUILD_STOCK = "reconcile.rebuild_stock_all"
REBUILD_RECENT_FACTS = "reconcile.rebuild_recent_facts_all"
CHECK_REVENUE = "reconcile.check_revenue_all"
ENSURE_PARTITIONS = "reconcile.ensure_audit_partitions"
PURGE_IDEMPOTENCY = "reconcile.purge_idempotency_keys"
SCAN_DUE_DEBTS = "notifications.scan_due_debts_all"
ML_FEATURES = "ml_features.compute_all"
ML_TRAIN = "ml_train.train_all"
ML_INFER = "ml_infer.infer_all"
SWEEP_EXPORTS = "exports.sweep_all"
#: Surveillance (ADR 0077).
BEAT_TICK = "system.beat_tick"
PURGE_JOB_RUNS = "system.purge_job_runs"
#: Abonnements (ADR 0091) : fin des essais, et sa sous-tâche par entreprise.
SUBSCRIPTIONS_DAILY = "platform.subscriptions_daily"
TRIAL_NOTICE = "platform.trial_notice"
#: Accès support (ADR 0092) : ferme à leur échéance les sessions restées ouvertes.
SUPPORT_SESSIONS_CLOSE = "platform.support_sessions_close"

#: Délai dur d'une tâche (`task_time_limit`). Une trace restée `running` au-delà est
#: celle d'un worker tué : la lecture la compte comme un échec.
TASK_TIME_LIMIT_SECONDS = 360

#: Intervalle de `system.beat_tick`, et délai au-delà duquel son silence est une panne.
BEAT_TICK_SECONDS = 300
BEAT_TICK_MAX_AGE = timedelta(minutes=15)

#: Nombre de jours de faits réécrits chaque nuit. C'est le filet du § 12.1 point 3 :
#: un événement perdu ne laisse pas un agrégat faux plus d'une nuit.
NIGHTLY_FACTS_WINDOW_DAYS = 7

#: Profondeur du contrôle de cohérence T32.
RECONCILIATION_WINDOW_DAYS = 90

BEAT_SCHEDULE: dict[str, dict[str, Any]] = {
    # 01 h 00 — les partitions du mois suivant, avant tout le reste. Une partition
    # manquante ferait échouer tout INSERT dans `audit_logs`, donc toute vente
    # (ADR 0008) : ce créneau passe en premier et ne dépend de rien.
    "ensure-audit-partitions": {
        "task": ENSURE_PARTITIONS,
        "schedule": crontab(hour="1", minute="0"),
    },
    # 01 h 30 — purge des clés d'idempotence expirées, la dette laissée par l'ADR 0027.
    "purge-idempotency-keys": {
        "task": PURGE_IDEMPOTENCY,
        "schedule": crontab(hour="1", minute="30"),
    },
    # 01 h 45 — exports : les fichiers de plus de 24 h sont vidés, et une demande
    # restée `pending` (Redis indisponible au moment de la demande) est renfilée
    # (ADR 0041). Nocturne seulement : un balayage fréquent réveillerait la base
    # Neon de préproduction (ADR 0040).
    "sweep-exports": {
        "task": SWEEP_EXPORTS,
        "schedule": crontab(hour="1", minute="45"),
    },
    # 02 h 00 — réalignement de la projection de stock sur le journal (§ 5.7).
    "rebuild-product-stock": {
        "task": REBUILD_STOCK,
        "schedule": crontab(hour="2", minute="0"),
    },
    # 03 h 00 — filet analytique : les sept derniers jours réécrits, quoi qu'il soit
    # arrivé aux événements de la journée.
    "rebuild-recent-facts": {
        "task": REBUILD_RECENT_FACTS,
        "schedule": crontab(hour="3", minute="0"),
    },
    # 03 h 30 — CoGes Intelligence, étapes 02-04 : photographie de la veille, après
    # le filet analytique de 03 h 00 (ADR 0035).
    "ml-features": {
        "task": ML_FEATURES,
        "schedule": crontab(hour="3", minute="30"),
    },
    # Lundi 03 h 45 — étape 05 : un modèle par entreprise et par semaine ISO.
    "ml-train": {
        "task": ML_TRAIN,
        "schedule": crontab(day_of_week="1", hour="3", minute="45"),
    },
    # 04 h 30 — étapes 06-07 : prévisions et insights, lus par l'API au réveil.
    "ml-infer": {
        "task": ML_INFER,
        "schedule": crontab(hour="4", minute="30"),
    },
    # 06 h 00 — dettes arrivées à échéance. Une dette échoit précisément quand rien
    # ne bouge : aucun événement ne peut déclencher cette alerte, seul un calendrier.
    "scan-due-debts": {
        "task": SCAN_DUE_DEBTS,
        "schedule": crontab(hour="6", minute="0"),
    },
    # Dimanche 04 h 00 — contrôle hebdomadaire T32 sur 90 jours (§ 12.1 point 3).
    "check-revenue-consistency": {
        "task": CHECK_REVENUE,
        "schedule": crontab(day_of_week="0", hour="4", minute="0"),
    },
    # 01 h 15 — purge des traces de tâches de plus de 90 jours (ADR 0077).
    "purge-job-runs": {
        "task": PURGE_JOB_RUNS,
        "schedule": crontab(hour="1", minute="15"),
    },
    # 06 h 30 — fin des essais (ADR 0091) : avertir à J-7, J-3, J-1, suspendre à
    # l'échéance. Après la nuit, avant l'ouverture des boutiques.
    "subscriptions-daily": {
        "task": SUBSCRIPTIONS_DAILY,
        "schedule": crontab(hour="6", minute="30"),
    },
    # 01 h 30 — accès support échus fermés (ADR 0092). Le jeton ne servait déjà plus :
    # la liste des sessions ouvertes redevient exacte.
    "support-sessions-close": {
        "task": SUPPORT_SESSIONS_CLOSE,
        "schedule": crontab(hour="1", minute="30"),
    },
    # Toutes les 5 min — « beat est vivant et un worker consomme ». Écrit dans Redis et
    # pingue, sans toucher la base, qui peut ainsi s'endormir en préproduction.
    "beat-tick": {
        "task": BEAT_TICK,
        "schedule": float(BEAT_TICK_SECONDS),
    },
}


@dataclass(frozen=True, slots=True)
class Freshness:
    """Délai dans lequel une tâche planifiée doit avoir réussi, et sa sous-tâche.

    `per_company` nomme la sous-tâche enfilée pour chaque entreprise : le bilan compte
    les entreprises dont la dernière exécution a échoué.
    """

    window: timedelta
    per_company: str | None = None


#: 26 h pour une tâche quotidienne (une nuit manquée, plus deux heures de marge),
#: 8 jours pour une hebdomadaire. Toute tâche de `BEAT_SCHEDULE` figure ici, sauf
#: `beat_tick`, suivie dans Redis (test d'architecture).
DAILY = timedelta(hours=26)
WEEKLY = timedelta(days=8)
JOB_FRESHNESS: dict[str, Freshness] = {
    ENSURE_PARTITIONS: Freshness(DAILY),
    PURGE_JOB_RUNS: Freshness(DAILY),
    PURGE_IDEMPOTENCY: Freshness(DAILY),
    SWEEP_EXPORTS: Freshness(DAILY, "exports.sweep"),
    REBUILD_STOCK: Freshness(DAILY, "reconcile.rebuild_stock"),
    REBUILD_RECENT_FACTS: Freshness(DAILY, "analytics.rebuild_recent_facts"),
    ML_FEATURES: Freshness(DAILY, "ml_features.compute"),
    ML_TRAIN: Freshness(WEEKLY, "ml_train.train"),
    ML_INFER: Freshness(DAILY, "ml_infer.infer"),
    SCAN_DUE_DEBTS: Freshness(DAILY, "notifications.scan_due_debts"),
    CHECK_REVENUE: Freshness(WEEKLY, "reconcile.check_revenue"),
    SUBSCRIPTIONS_DAILY: Freshness(DAILY, TRIAL_NOTICE),
    SUPPORT_SESSIONS_CLOSE: Freshness(DAILY),
}
