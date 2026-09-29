import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { formatMoney } from "@/lib/format";

import { DataTable, type Column } from "./data-table";

type Row = { id: string; name: string; total: string };

const columns: Column<Row>[] = [
  { id: "name", header: "Produit", cell: (row) => row.name, sortable: true },
  { id: "total", header: "Total", cell: (row) => formatMoney(row.total), numeric: true },
];

const rows: Row[] = [
  { id: "1", name: "Riz 25 kg", total: "1250000.00" },
  { id: "2", name: "Huile 5 L", total: "4500.00" },
];

function renderTable(props: Partial<Parameters<typeof DataTable<Row>>[0]> = {}) {
  const onPageChange = vi.fn();
  const onSortChange = vi.fn();
  render(
    <DataTable<Row>
      caption="Produits"
      columns={columns}
      rows={rows}
      rowKey={(row) => row.id}
      total={45}
      page={2}
      pageSize={20}
      onPageChange={onPageChange}
      sort={null}
      onSortChange={onSortChange}
      {...props}
    />,
  );
  return { onPageChange, onSortChange };
}

describe("DataTable", () => {
  it("aligne les montants à droite, sans retour à la ligne", () => {
    renderTable();
    const cell = screen.getByText(formatMoney("1250000.00"), {
      normalizer: (text) => text, // garder les espaces insécables
    });
    expect(cell).toHaveClass("text-right", "numeric");
    expect(screen.getByRole("columnheader", { name: "Total" })).toHaveClass("text-right");
  });

  it("délègue la pagination au serveur", async () => {
    const { onPageChange } = renderTable();
    expect(screen.getByText("Page 2 sur 3")).toBeInTheDocument();
    expect(screen.getByText("45 éléments")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Page suivante" }));
    await userEvent.click(screen.getByRole("button", { name: "Page précédente" }));
    expect(onPageChange.mock.calls).toEqual([[3], [1]]);
  });

  it("désactive « suivante » sur la dernière page", () => {
    renderTable({ page: 3 });
    expect(screen.getByRole("button", { name: "Page suivante" })).toBeDisabled();
  });

  it("émet le tri sans trier lui-même, et seulement sur les colonnes triables", async () => {
    const { onSortChange } = renderTable();
    await userEvent.click(screen.getByRole("button", { name: /Produit/ }));
    expect(onSortChange).toHaveBeenCalledWith({ id: "name", direction: "asc" });
    const totalHeader = screen.getByRole("columnheader", { name: "Total" });
    expect(within(totalHeader).queryByRole("button")).toBeNull();
    // L'ordre des lignes reste celui de l'API.
    const body = screen.getAllByRole("row").slice(1);
    expect(body.map((row) => within(row).getAllByRole("cell")[0]?.textContent)).toEqual([
      "Riz 25 kg",
      "Huile 5 L",
    ]);
  });

  it("affiche un état vide", () => {
    renderTable({ rows: [], total: 0, page: 1 });
    expect(screen.getByText("Aucun élément à afficher.")).toBeInTheDocument();
  });

  it("rend les lignes cliquables au clavier", async () => {
    const onRowClick = vi.fn();
    renderTable({ onRowClick });
    const row = screen.getByText("Huile 5 L").closest("tr");
    row?.focus();
    await userEvent.keyboard("{Enter}");
    expect(onRowClick).toHaveBeenCalledWith(rows[1]);
  });
});
