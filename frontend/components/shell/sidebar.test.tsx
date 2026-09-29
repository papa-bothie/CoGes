import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SidebarContent } from "./sidebar";

describe("SidebarContent", () => {
  it("affiche le nom de l'entreprise, sans sélecteur, et masque ce qui est interdit", () => {
    render(
      <SidebarContent
        companyName="Boutique Awa"
        permissions={["dashboard:read", "sales:read"]}
        pathname="/sales/new"
      />,
    );
    expect(screen.getByText("Boutique Awa")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(["Tableau de bord", "Ventes"]);
    expect(screen.getByRole("link", { name: "Ventes" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("link", { name: "Paramètres" })).toBeNull();
  });
});
