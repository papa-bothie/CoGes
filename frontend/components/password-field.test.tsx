import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { PasswordField } from "./password-field";

function Harness() {
  const [submitted, setSubmitted] = useState(0);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        setSubmitted((count) => count + 1);
      }}
    >
      <PasswordField label="Mot de passe" autoComplete="current-password" submitted={submitted} />
      <button type="submit">Envoyer</button>
    </form>
  );
}

const field = () => screen.getByLabelText("Mot de passe", { selector: "input" });

describe("PasswordField", () => {
  it("masque par défaut, avec le bon autocomplete", () => {
    render(<Harness />);
    expect(field()).toHaveAttribute("type", "password");
    expect(field()).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByRole("button", { name: "Afficher le mot de passe" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("affiche puis cache, sans perdre ce qui est tapé", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(field(), "une phrase secrète");
    await user.click(screen.getByRole("button", { name: "Afficher le mot de passe" }));
    expect(field()).toHaveAttribute("type", "text");
    expect(field()).toHaveValue("une phrase secrète");
    const hide = screen.getByRole("button", { name: "Cacher le mot de passe" });
    expect(hide).toHaveAttribute("aria-pressed", "true");
    await user.click(hide);
    expect(field()).toHaveAttribute("type", "password");
    expect(field()).toHaveValue("une phrase secrète");
  });

  it("se remasque à l'envoi du formulaire", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(field(), "secret");
    await user.click(screen.getByRole("button", { name: "Afficher le mot de passe" }));
    await user.click(screen.getByRole("button", { name: "Envoyer" }));
    expect(field()).toHaveAttribute("type", "password");
    expect(field()).toHaveValue("secret");
  });

  it("se remasque quand l'onglet est caché", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Afficher le mot de passe" }));
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(field()).toHaveAttribute("type", "password");
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
  });

  it("le bouton ne soumet pas le formulaire", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Afficher le mot de passe" }));
    // Toujours affiché : aucun envoi n'a eu lieu.
    expect(field()).toHaveAttribute("type", "text");
  });
});
