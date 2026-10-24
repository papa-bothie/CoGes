/**
 * Mots de l'écran Système (ADR 0090). Les codes viennent de `GET /system/workers`
 * (ADR 0077) ; l'écran les dit en français **et** montre le code exact, celui que cite
 * le guide `docs/runbooks/workers.md`.
 */

export const COMPONENT_LABELS: Record<string, string> = {
  worker: "Worker (tâches)",
  beat: "Beat (planificateur)",
  relay: "Relais des événements",
};

/** Tâches planifiées de `backend/app/workers/beat.py`, et leurs sous-tâches. */
const JOB_LABELS: Record<string, string> = {
  "reconcile.rebuild_stock_all": "Recalcul du stock",
  "reconcile.rebuild_stock": "Recalcul du stock",
  "reconcile.rebuild_recent_facts_all": "Agrégats des ventes",
  "analytics.rebuild_recent_facts": "Agrégats des ventes",
  "reconcile.check_revenue_all": "Contrôle du chiffre d'affaires",
  "reconcile.check_revenue": "Contrôle du chiffre d'affaires",
  "reconcile.ensure_audit_partitions": "Partitions du journal d'audit",
  "reconcile.purge_idempotency_keys": "Purge des clés d'idempotence",
  "notifications.scan_due_debts_all": "Dettes arrivées à échéance",
  "notifications.scan_due_debts": "Dettes arrivées à échéance",
  "ml_features.compute_all": "Intelligence : préparation",
  "ml_features.compute": "Intelligence : préparation",
  "ml_train.train_all": "Intelligence : entraînement",
  "ml_train.train": "Intelligence : entraînement",
  "ml_infer.infer_all": "Intelligence : prévisions",
  "ml_infer.infer": "Intelligence : prévisions",
  "exports.sweep_all": "Purge des exports",
  "exports.sweep": "Purge des exports",
  "system.purge_job_runs": "Purge de l'historique des tâches",
  "platform.subscriptions_daily": "Fin des essais",
  "platform.trial_notice": "Fin des essais",
};

export function jobLabel(job: string): string {
  return JOB_LABELS[job] ?? job;
}

export const JOB_STATE_LABELS: Record<string, string> = {
  ok: "Réussie dans sa fenêtre",
  never_ran: "Jamais exécutée",
  stale: "Pas de réussite dans sa fenêtre",
  failed: "Dernière exécution en échec",
  companies_failed: "En échec pour au moins une entreprise",
};

export const RUN_STATUS_LABELS: Record<string, string> = {
  ok: "Réussie",
  failed: "En échec",
  running: "En cours",
};

/** Un code de `problems` en phrase : `heartbeat_missing:worker` → « Battement absent… ». */
export function describeProblem(code: string): string {
  const [kind, subject = ""] = splitOnce(code);
  switch (kind) {
    case "redis_unreachable":
      return "Redis ne répond pas : battements et file d'attente illisibles";
    case "heartbeat_missing":
      return `Battement absent : ${COMPONENT_LABELS[subject] ?? subject}`;
    case "beat_tick_missing":
      return "Le planificateur ne fait plus tourner de tâche";
    case "outbox_lagging":
      return "Des événements attendent trop longtemps d'être publiés";
    case "outbox_dead_lettered": {
      const count = Number(subject);
      return `${count} événement${count > 1 ? "s" : ""} au rebut, à rejouer à la main`;
    }
    case "job_failed":
    case "job_stale":
    case "job_never_ran":
    case "job_companies_failed":
      return `${JOB_STATE_LABELS[kind.slice(4)]} : ${jobLabel(subject)}`;
    default:
      return code;
  }
}

function splitOnce(code: string): [string, string?] {
  const at = code.indexOf(":");
  return at < 0 ? [code] : [code.slice(0, at), code.slice(at + 1)];
}
