import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { SegmentedControl } from "./segmented-control";

function Filter() {
  const [value, setValue] = useState<"all" | "unread">("all");
  return (
    <SegmentedControl
      aria-label="Afficher"
      value={value}
      onValueChange={setValue}
      options={[
        { value: "all", label: "Toutes" },
        { value: "unread", label: "Non lues" },
      ]}
    />
  );
}

describe("SegmentedControl", () => {
  it("est un groupe de boutons radio, sans onglet", () => {
    render(<Filter />);
    expect(screen.getByRole("radiogroup", { name: "Afficher" })).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Toutes" })).toHaveAttribute("aria-checked", "true");
  });

  it("n'offre qu'un arrêt de tabulation et se pilote aux flèches", () => {
    render(<Filter />);
    const all = screen.getByRole("radio", { name: "Toutes" });
    const unread = screen.getByRole("radio", { name: "Non lues" });
    expect(all).toHaveAttribute("tabindex", "0");
    expect(unread).toHaveAttribute("tabindex", "-1");

    fireEvent.keyDown(all, { key: "ArrowRight" });
    expect(unread).toHaveAttribute("aria-checked", "true");
    expect(unread).toHaveFocus();

    // On boucle : après le dernier, le premier.
    fireEvent.keyDown(unread, { key: "ArrowRight" });
    expect(all).toHaveAttribute("aria-checked", "true");

    fireEvent.keyDown(all, { key: "End" });
    expect(unread).toHaveAttribute("aria-checked", "true");
  });
});
