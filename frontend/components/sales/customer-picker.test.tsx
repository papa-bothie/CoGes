import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { CustomerPicker, initials } from "./customer-picker";

const PAGE = {
  items: [
    { id: "c1", name: "Moussa Fall", phone: "76 220 15 90", open_debt: "25000.00", recent: true },
    { id: "c2", name: "Awa Diop", phone: "77 412 08 33", open_debt: "0.00", recent: false },
    { id: "c3", name: "Boutique Ndiaye", phone: null, open_debt: "0.00", recent: false },
  ],
  page: 1,
  page_size: 50,
  total: 3,
};

vi.mock("@/lib/api/client", () => ({
  api: { GET: vi.fn(async () => PAGE), POST: vi.fn(), PATCH: vi.fn() },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

beforeAll(() => {
  // jsdom n'a pas ResizeObserver, que le positionnement du Popover observe.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

function renderPicker(onSelect = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <div data-testid="carte" style={{ overflow: "hidden" }}>
        <CustomerPicker onSelect={onSelect} currency="XOF" />
      </div>
    </QueryClientProvider>,
  );
  return onSelect;
}

describe("CustomerPicker", () => {
  it("ouvre la liste hors de la carte, jamais sous un parent `overflow: hidden`", async () => {
    renderPicker();
    await userEvent.click(screen.getByRole("combobox", { name: /Rechercher un client/ }));
    const list = await screen.findByRole("listbox");

    expect(screen.getByTestId("carte")).not.toContainElement(list);
    for (let node = list.parentElement; node; node = node.parentElement) {
      expect(getComputedStyle(node).overflow).not.toBe("hidden");
    }
  });

  it("montre le client de passage, puis les clients dans l'ordre du serveur", async () => {
    renderPicker();
    await userEvent.click(screen.getByRole("combobox", { name: /Rechercher un client/ }));
    await screen.findByText("Moussa Fall");

    const names = screen
      .getAllByRole("option")
      .map((option) => option.querySelector(".font-medium")?.textContent);
    expect(names).toEqual(["Client de passage", "Moussa Fall", "Awa Diop", "Boutique Ndiaye"]);
  });

  it("dit ce que doit le client, et rien pour qui ne doit rien", async () => {
    renderPicker();
    await userEvent.click(screen.getByRole("combobox", { name: /Rechercher un client/ }));
    const moussa = (await screen.findByText("Moussa Fall")).closest("[role=option]")!;
    expect(moussa).toHaveTextContent("Doit 25 000 FCFA");
    expect(moussa).toHaveTextContent("76 220 15 90");
    const awa = screen.getByText("Awa Diop").closest("[role=option]")!;
    expect(awa).not.toHaveTextContent("Doit");
  });

  it("choisit un client, ou le client de passage", async () => {
    const onSelect = renderPicker();
    const input = screen.getByRole("combobox", { name: /Rechercher un client/ });
    await userEvent.click(input);
    await userEvent.click(await screen.findByText("Awa Diop"));
    expect(onSelect).toHaveBeenLastCalledWith({
      id: "c2",
      name: "Awa Diop",
      phone: "77 412 08 33",
    });

    await userEvent.click(input);
    await userEvent.click(await screen.findByText("Client de passage"));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("propose « Nouveau client » en bas de la liste", async () => {
    renderPicker();
    await userEvent.click(screen.getByRole("combobox", { name: /Rechercher un client/ }));
    await screen.findByText("Moussa Fall");
    const button = screen.getByRole("button", { name: "Nouveau client" });
    await userEvent.click(button);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getAllByRole("textbox").length).toBeGreaterThan(0);
  });
});

describe("initials", () => {
  it("prend les deux premières initiales", () => {
    expect(initials("Moussa Fall")).toBe("MF");
    expect(initials("boutique serigne mbaye")).toBe("BS");
    expect(initials("Awa")).toBe("A");
  });
});
