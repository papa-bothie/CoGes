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
}
