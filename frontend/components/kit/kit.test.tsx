import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ShoppingCart } from "lucide-react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { AmountField, cleanAmount, NumericPad } from "./amount-field";
import { BottomNav, TopBar, type BarItem } from "./app-bars";
import { Chip } from "./chip";
import { ChoiceGroup } from "./choice-group";
import { DayBars } from "./day-bars";
import { Avatar, initials, personTone, ProductSquare } from "./list-row";
import { cleanQuantity, QuantityStepper } from "./quantity-stepper";
import { StatTile } from "./stat-tile";
import { StatusPill } from "./status-pill";

function AmountWithPad({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <AmountField label="Il donne maintenant" value={value} onChange={setValue} />
      <NumericPad value={value} onChange={setValue} />
    </>
  );
}

describe("champ montant et pavé numérique", () => {
  it("ne garde que des chiffres, sans zéro de tête ni décimales", () => {
    expect(cleanAmount("007 500")).toBe("7500");
    expect(cleanAmount("12,50")).toBe("1250");
    expect(cleanAmount("0")).toBe("0");
    expect(cleanAmount("9".repeat(20))).toHaveLength(12);
  });

  it("se tape librement au clavier", async () => {
    render(<AmountWithPad />);
    const field = screen.getByLabelText("Il donne maintenant");
    await userEvent.type(field, "7a5 00");
    expect(field).toHaveValue("7500");
  });

  it("le pavé ajoute, multiplie par mille et efface", async () => {
    render(<AmountWithPad />);
    const field = screen.getByLabelText("Il donne maintenant");
    await userEvent.click(screen.getByRole("button", { name: "7" }));
    await userEvent.click(screen.getByRole("button", { name: "5" }));
    await userEvent.click(screen.getByRole("button", { name: "000" }));
    expect(field).toHaveValue("75000");
    await userEvent.click(screen.getByRole("button", { name: "Effacer le dernier chiffre" }));
    expect(field).toHaveValue("7500");
  });

  it("chaque touche du pavé fait au moins 56 px (classe min-h-touche)", () => {
    render(<AmountWithPad />);
    expect(screen.getByRole("button", { name: "1" }).className).toContain("min-h-touche");
  });
});

function Stepper() {
  const [value, setValue] = useState("1");
  return <QuantityStepper value={value} onChange={setValue} itemName="Huile Dinor 1 L" min={1} />;
}

describe("champ quantité", () => {
  it("accepte une virgule et trois décimales au plus", () => {
    expect(cleanQuantity("2.5")).toBe("2,5");
    expect(cleanQuantity("1,23456")).toBe("1,234");
    expect(cleanQuantity("abc")).toBe("");
  });

  it("− et + ne sont que des raccourcis ; − se bloque au minimum", async () => {
    render(<Stepper />);
    const field = screen.getByLabelText("Quantité : Huile Dinor 1 L");
    const less = screen.getByRole("button", { name: "Retirer un Huile Dinor 1 L" });
    expect(less).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Ajouter un Huile Dinor 1 L" }));
    expect(field).toHaveValue("2");
    await userEvent.clear(field);
    await userEvent.type(field, "12");
    expect(field).toHaveValue("12");
  });
});

describe("pastille d'état", () => {
  it("écrit les états de la maquette", () => {
    render(
      <>
        <StatusPill status="paid" />
        <StatusPill status="remaining" amount="10 000 F" />
        <StatusPill status="returned" amount="5 000 F" />
        <StatusPill status="cancelled" />
      </>,
    );
    expect(screen.getByText("Payé").className).toContain("bg-ventes-teinte");
    expect(screen.getByText("Reste 10 000 F").className).toContain("text-stock-encre");
    expect(screen.getByText("Retour : 5 000 F").className).toContain("bg-argent-teinte");
    expect(screen.getByText("Annulée")).toBeInTheDocument();
  });
});

describe("puce et grand choix", () => {
  it("la puce dit si elle est choisie", () => {
    render(
      <>
        <Chip selected>Tout</Chip>
        <Chip>Huiles</Chip>
      </>,
    );
    expect(screen.getByRole("button", { name: "Tout" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Huiles" })).toHaveAttribute("aria-pressed", "false");
  });

  it("le grand choix est un groupe radio exclusif", async () => {
    function Payment() {
      const [value, setValue] = useState<"all" | "credit">("all");
      return (
        <ChoiceGroup
          label="Le client paie"
          value={value}
          onValueChange={setValue}
          choices={[
            { value: "all", label: "Tout payé" },
            { value: "credit", label: "À crédit" },
          ]}
        />
      );
    }
    render(<Payment />);
    expect(screen.getByRole("radiogroup", { name: "Le client paie" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "À crédit" }));
    expect(screen.getByRole("radio", { name: "À crédit" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Tout payé" })).not.toBeChecked();
  });
});

describe("avatars et carrés d'article", () => {
  it("tire les initiales et une couleur stable du nom", () => {
    expect(initials("Awa Diop")).toBe("AD");
    expect(initials("  moussa  ")).toBe("M");
    expect(personTone("Moussa Fall")).toBe(personTone("Moussa Fall"));
  });

  it("un client de passage n'a pas d'initiales", () => {
    const { container } = render(<Avatar name={null} />);
    expect(container.textContent).toBe("·");
  });

  it("le carré d'article montre la première lettre sur sa couleur", () => {
    const { container } = render(<ProductSquare name="riz brisé 25 kg" tone={1} />);
    expect(container.textContent).toBe("R");
    expect(container.firstElementChild?.className).toContain("bg-article-1");
  });
});

describe("tuile chiffrée et barres", () => {
  it("la tuile cliquable est un lien", () => {
    render(
      <StatTile
        rubrique="ventes"
        icon={ShoppingCart}
        label="Vendu aujourd'hui"
        value="87 500 F"
        detail="14 ventes"
        href="/sales"
      />,
    );
    expect(screen.getByRole("link", { name: /Vendu aujourd'hui/ })).toHaveAttribute(
      "href",
      "/sales",
    );
  });

  it("chaque barre se lit avec son jour", () => {
    render(
      <DayBars
        label="Ventes des 7 derniers jours"
        bars={[
          { label: "Lun", display: "80 500", weight: 80500 },
          { label: "Aujourd'hui", display: "87 500", weight: 87500, current: true },
        ]}
      />,
    );
    const list = screen.getByRole("list", { name: "Ventes des 7 derniers jours" });
    expect(list).toHaveTextContent("Aujourd'hui : 87 500");
  });
});

describe("barres de navigation", () => {
  const items: BarItem[] = [
    { href: "/dashboard", label: "Accueil", icon: ShoppingCart, rubrique: "ventes", active: true },
    { href: "/sales", label: "Vendre", icon: ShoppingCart, rubrique: "ventes", active: false },
  ];

  it("la barre du haut marque l'onglet actif à la couleur de sa rubrique", () => {
    render(<TopBar companyName="Alimentation Keur Fatou" items={items} />);
    const active = screen.getByRole("link", { name: "Accueil" });
    expect(active).toHaveAttribute("aria-current", "page");
    expect(active.className).toContain("bg-ventes-teinte");
    expect(screen.getByRole("link", { name: "Vendre" })).not.toHaveAttribute("aria-current");
  });

  it("la barre basse garde des cibles de 64 px", () => {
    render(<BottomNav items={items} />);
    expect(screen.getByRole("link", { name: "Vendre" }).className).toContain("min-h-16");
  });
});
