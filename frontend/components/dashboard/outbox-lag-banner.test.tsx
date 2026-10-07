import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { isOutboxLagging, OUTBOX_LAG_MS, OutboxLagBanner } from "./outbox-lag-banner";

const state = vi.hoisted(() => ({ allowed: true, lagging: false }));

vi.mock("@/hooks/use-permission", () => ({ usePermission: () => state.allowed }));
vi.mock("@tanstack/react-query", () => ({
  useQuery: ({ enabled }: { enabled: boolean }) => ({ data: enabled && state.lagging }),
}));

const MESSAGE = "Certains chiffres se mettent à jour, patientez une minute.";

describe("isOutboxLagging", () => {
  const now = Date.parse("2026-10-06T10:45:00Z");

  it("reste muet sans événement en attente", () => {
    expect(isOutboxLagging(null, now)).toBe(false);
  });

  it("reste muet sous deux minutes, parle au-delà", () => {
    expect(isOutboxLagging(new Date(now - OUTBOX_LAG_MS).toISOString(), now)).toBe(false);
    expect(isOutboxLagging(new Date(now - OUTBOX_LAG_MS - 1000).toISOString(), now)).toBe(true);
  });
});

describe("OutboxLagBanner", () => {
  beforeEach(() => {
    state.allowed = true;
    state.lagging = true;
  });

  it("prévient le gérant quand l'outbox attend", () => {
    render(<OutboxLagBanner />);
    expect(screen.getByRole("status")).toHaveTextContent(MESSAGE);
  });

  it("ne montre rien à un vendeur", () => {
    state.allowed = false;
    const { container } = render(<OutboxLagBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("ne montre rien quand tout est publié", () => {
    state.lagging = false;
    const { container } = render(<OutboxLagBanner />);
    expect(container).toBeEmptyDOMElement();
  });
});
