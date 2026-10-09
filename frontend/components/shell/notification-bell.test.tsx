import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NotificationBell } from "./notification-bell";

const counter = vi.hoisted(() => ({ value: { unread: 3, critical: 0 } }));

vi.mock("@/hooks/use-me", () => ({
  useMe: () => ({ data: { permissions: ["notifications:read"] } }),
}));
vi.mock("@/lib/api/client", () => ({
  api: { GET: vi.fn(async () => counter.value) },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

function renderBell() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NotificationBell />
    </QueryClientProvider>,
  );
}

describe("NotificationBell", () => {
  it("ne montre pas de badge sans alerte grave, mais compte les non lues dans son nom", async () => {
    counter.value = { unread: 3, critical: 0 };
    renderBell();
    const link = await screen.findByRole("link", { name: "Alertes, 3 non lues" });
    expect(link).toHaveAttribute("href", "/notifications");
    expect(link.textContent).toBe("");
  });

  it("montre le badge dès qu'une alerte grave n'est pas lue", async () => {
    counter.value = { unread: 3, critical: 1 };
    renderBell();
    const link = await screen.findByRole("link", { name: "Alertes, 3 non lues" });
    expect(link.textContent).toBe("3");
  });
});
