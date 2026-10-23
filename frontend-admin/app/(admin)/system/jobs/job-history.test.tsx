import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { JobRunPage } from "@/lib/api/schema";

import { JobHistory } from "./job-history";

const PAGE: JobRunPage = {
  items: [
    {
      id: 2,
      job: "reconcile.rebuild_stock_all",
      status: "failed",
      started_at: "2026-10-06T02:00:00Z",
      finished_at: "2026-10-06T02:00:03Z",
      error: "OperationalError (08006)",
      per_company: false,
    },
    {
      id: 1,
      job: "exports.sweep_all",
      status: "ok",
      started_at: "2026-10-06T01:00:00Z",
      finished_at: "2026-10-06T01:00:01Z",
      error: null,
      per_company: false,
    },
  ],
  page: 1,
  page_size: 50,
  total: 2,
};

const GET = vi.fn(async () => ({ data: PAGE, response: new Response(null, { status: 200 }) }));

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  api: { GET: (...args: unknown[]) => GET(...(args as [])) },
}));

describe("historique des tâches", () => {
  it("un clic sur une ligne en échec montre le message court", async () => {
    render(<JobHistory />);
    const row = (await screen.findByText("Recalcul du stock")).closest("tr");
    expect(screen.queryByText("OperationalError (08006)")).toBeNull();
    await userEvent.click(row!);
    expect(screen.getByText("OperationalError (08006)")).toBeVisible();
    // Le bouton, au clavier, referme.
    await userEvent.click(screen.getByRole("button", { name: /Masquer l'erreur/ }));
    expect(screen.queryByText("OperationalError (08006)")).toBeNull();
  });

  it("une ligne réussie n'a rien à ouvrir", async () => {
    render(<JobHistory />);
    await screen.findByText("Purge des exports");
    expect(screen.getAllByRole("button", { name: /Voir l'erreur/ })).toHaveLength(1);
  });

  it("le filtre de statut part au serveur", async () => {
    render(<JobHistory />);
    await screen.findByText("Recalcul du stock");
    await userEvent.selectOptions(screen.getByLabelText("Statut"), "failed");
    expect(GET).toHaveBeenLastCalledWith("/api/v1/platform/system/job-runs", {
      params: { query: { page: 1, page_size: 50, status: "failed", job: undefined } },
    });
  });
});
