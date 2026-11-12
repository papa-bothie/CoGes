import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/schema";
import { renderWithClient } from "@/test/render";

import { CorrectSale, secondsLeft } from "./correct-sale";

const push = vi.fn();
let allowed = true;

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/hooks/use-permission", () => ({ usePermission: () => allowed }));
vi.mock("@/lib/api/client", () => ({
  api: { POST: vi.fn(async () => ({ id: "brouillon-43" })) },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

function sale(seconds: number | null): Schemas["SaleRead"] {
  return {
    id: "vente-42",
    sale_no: "V-000042",
    correction_seconds_left: seconds,
  } as Schemas["SaleRead"];
}

beforeEach(() => {
  allowed = true;
  push.mockClear();
  vi.mocked(api.POST).mockClear();
});
afterEach(() => vi.useRealTimers());

describe("secondsLeft", () => {
  it("décompte depuis la réponse du serveur, jamais depuis l'heure du téléphone", () => {
    expect(secondsLeft(420, 1_000, 1_000)).toBe(420);
    expect(secondsLeft(420, 1_000, 61_500)).toBe(360);
    expect(secondsLeft(420, 1_000, 421_000)).toBeNull();
    expect(secondsLeft(null, 1_000, 1_000)).toBeNull();
    // Un téléphone dont l'horloge recule ne rallonge pas le délai.
    expect(secondsLeft(420, 10_000, 5_000)).toBe(420);
  });
});

describe("Corriger cette vente", () => {
  it("dit le temps qui reste", () => {
    renderWithClient(<CorrectSale sale={sale(7 * 60 - 5)} receivedAt={Date.now()} />);
    expect(screen.getByRole("button", { name: /Corriger cette vente/ })).toHaveTextContent(
      "encore 7 min",
    );
  });

  it("disparaît une fois le délai passé", () => {
    vi.useFakeTimers();
    const now = Date.now();
    renderWithClient(<CorrectSale sale={sale(2)} receivedAt={now} />);
    expect(screen.getByRole("button", { name: /moins d'une minute/ })).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(3_000);
    });
    expect(screen.queryByRole("button", { name: /Corriger/ })).not.toBeInTheDocument();
  });

  it("n'apparaît ni hors délai, ni sans le droit de vendre", () => {
    const { unmount } = renderWithClient(<CorrectSale sale={sale(null)} receivedAt={0} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    unmount();
    allowed = false;
    renderWithClient(<CorrectSale sale={sale(300)} receivedAt={Date.now()} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("prévient avant d'annuler, puis ouvre le brouillon de la correction", async () => {
    const user = userEvent.setup();
    renderWithClient(<CorrectSale sale={sale(300)} receivedAt={Date.now()} />);
    await user.click(screen.getByRole("button", { name: /Corriger cette vente/ }));
    expect(
      screen.getByText(
        "La vente n° 42 sera annulée. Vous la referez, puis vous encaisserez de nouveau.",
      ),
    ).toBeInTheDocument();
    expect(api.POST).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Oui, corriger" }));
    expect(api.POST).toHaveBeenCalledTimes(1);
    const [path, init] = vi.mocked(api.POST).mock.calls[0] as unknown as [
      string,
      { headers: Record<string, string> },
    ];
    expect(path).toBe("/api/v1/sales/{sale_id}/correct");
    expect(init.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(push).toHaveBeenCalledWith("/sales/brouillon-43/edit");
  });

  it("« Non » garde la vente", async () => {
    const user = userEvent.setup();
    renderWithClient(<CorrectSale sale={sale(300)} receivedAt={Date.now()} />);
    await user.click(screen.getByRole("button", { name: /Corriger cette vente/ }));
    await user.click(screen.getByRole("button", { name: "Non, garder la vente" }));
    expect(api.POST).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Corriger cette vente/ })).toBeInTheDocument();
  });

  it("déjà corrigée par quelqu'un d'autre : mène à son brouillon", async () => {
    vi.mocked(api.POST).mockRejectedValueOnce(
      new ApiError(409, "sale_already_corrected", "Cette vente a déjà été corrigée.", {
        draft_id: "brouillon-autre",
      }),
    );
    const user = userEvent.setup();
    renderWithClient(<CorrectSale sale={sale(300)} receivedAt={Date.now()} />);
    await user.click(screen.getByRole("button", { name: /Corriger cette vente/ }));
    await user.click(screen.getByRole("button", { name: "Oui, corriger" }));
    expect(await screen.findByText("Cette vente a déjà été corrigée.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ouvrir la correction" })).toHaveAttribute(
      "href",
      "/sales/brouillon-autre/edit",
    );
    expect(push).not.toHaveBeenCalled();
  });
});
