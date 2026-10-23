import { describe, expect, it } from "vitest";

import { describeProblem, jobLabel } from "./system";

describe("motifs de panne en mots", () => {
  it.each([
    ["heartbeat_missing:worker", "Battement absent : Worker (tâches)"],
    ["beat_tick_missing", "Le planificateur ne fait plus tourner de tâche"],
    ["outbox_dead_lettered:1", "1 événement au rebut, à rejouer à la main"],
    ["outbox_dead_lettered:3", "3 événements au rebut, à rejouer à la main"],
    ["job_failed:reconcile.rebuild_stock_all", "Dernière exécution en échec : Recalcul du stock"],
    [
      "job_companies_failed:ml_infer.infer_all",
      "En échec pour au moins une entreprise : Intelligence : prévisions",
    ],
  ])("%s", (code, text) => {
    expect(describeProblem(code)).toBe(text);
  });

  it("un code inconnu reste lisible tel quel", () => {
    expect(describeProblem("nouveau_motif:x")).toBe("nouveau_motif:x");
    expect(jobLabel("tache.inconnue")).toBe("tache.inconnue");
  });
});
