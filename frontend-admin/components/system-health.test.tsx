import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { WorkersHealth } from "@/lib/api/schema";

import {
  SystemAlert,
  SystemHealthProvider,
  useSystemHealth,
  type HealthState,
} from "./system-health";

const BROKEN: WorkersHealth = {
  healthy: false,
  checked_at: "2026-10-06T10:45:00Z",
  problems: ["heartbeat_missing:worker", "outbox_dead_lettered:2"],
  components: [],
  beat_tick_age_seconds: 12,
  outbox: null,
  queue: { name: "celery", length: 0 },
  jobs: [],
};

function Banner() {
  return <SystemAlert state={useSystemHealth().state} />;
}

function renderWith(state: HealthState) {
  return render(
    <SystemHealthProvider read={async () => state}>
      <Banner />
      <p>Écran Entreprises</p>
    </SystemHealthProvider>,
  );
}

describe("bandeau de panne", () => {
  it("503 : bandeau rouge avec chaque motif en mots et son code exact", async () => {
    renderWith({ kind: "down", health: BROKEN });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Le système est en panne.");
    expect(alert).toHaveTextContent("Battement absent : Worker (tâches)");
    expect(alert).toHaveTextContent("(heartbeat_missing:worker)");
    expect(alert).toHaveTextContent("2 événements au rebut");
    expect(screen.getByRole("link", { name: "Voir l'état du système" })).toHaveAttribute(
      "href",
      "/system",
    );
    expect(screen.getByText("Écran Entreprises")).toBeVisible();
  });

  it("200 : aucun bandeau", async () => {
    renderWith({ kind: "ok", health: { ...BROKEN, healthy: true, problems: [] } });
    await screen.findByText("Écran Entreprises");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("serveur injoignable : état inconnu, pas une fausse panne", async () => {
    renderWith({ kind: "unknown", message: "Connexion impossible au serveur." });
    expect(await screen.findByText(/État du système inconnu/)).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
