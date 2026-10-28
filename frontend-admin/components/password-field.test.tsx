import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { PasswordField } from "./password-field";

function Harness() {
  const [value, setValue] = useState("");
  const [submitted, setSubmitted] = useState(0);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        setSubmitted((count) => count + 1);
      }}
    >
      <PasswordField
        label="Mot de passe"
        autoComplete="current-password"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        submitted={submitted}
      />
      <button type="submit">Se connecter</button>
    </form>
  );
}

const field = () => screen.getByLabelText("Mot de passe", { exact: true });

describe("PasswordField (administration)", () => {
  it("bascule sans perdre la valeur, puis se remasque à l'envoi", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(field(), "secret de l'équipe");
    const show = screen.getByRole("button", { name: "Afficher le mot de passe" });
    expect(show).toHaveAttribute("aria-pressed", "false");
    await user.click(show);
    expect(field()).toHaveAttribute("type", "text");
    expect(field()).toHaveValue("secret de l'équipe");
    expect(screen.getByRole("button", { name: "Cacher le mot de passe" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(field()).toHaveAttribute("type", "password");
    expect(field()).toHaveValue("secret de l'équipe");
  });
});
