import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VerifyLink } from "./verify-link";

const verify = vi.fn();
vi.mock("@/lib/signup/api", async (original) => ({
  ...(await original<typeof import("@/lib/signup/api")>()),
  verifySignupLink: (...args: unknown[]) => verify(...args),
  resendSignupLink: vi.fn(async () => ({})),
}));

beforeEach(() => {
  verify.mockReset();
  window.history.replaceState(null, "", "/verification/jeton-de-test-0000000000000");
});

describe("lien de vérification (ADR 0118)", () => {
  it("prêt : code de boutique affiché, connexion préremplie, jeton retiré de l'adresse", async () => {
    verify.mockResolvedValue({ status: "ready", company_slug: "epicerie-awa", message: "…" });
    render(<VerifyLink token="jeton-pret-000000000000000000" />);
    expect(await screen.findByRole("heading", { name: "Votre boutique est prête" })).toHaveFocus();
    expect(screen.getByText("epicerie-awa")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Me connecter" })).toHaveAttribute(
      "href",
      "/login?boutique=epicerie-awa",
    );
    expect(window.location.pathname).toBe("/verification");
  });

  it("le même jeton n'est envoyé qu'une fois, même rendu deux fois", async () => {
    verify.mockResolvedValue({ status: "ready", company_slug: "x-shop", message: "…" });
    const token = "jeton-unique-0000000000000000";
    render(<VerifyLink token={token} />);
    render(<VerifyLink token={token} />);
    await screen.findAllByRole("heading", { name: "Votre boutique est prête" });
    expect(verify).toHaveBeenCalledTimes(1);
  });

  it("invalide : un seul message, et un nouveau lien possible", async () => {
    verify.mockRejectedValue(new Error("signup_link_invalid"));
    render(<VerifyLink token="jeton-perime-00000000000000000" />);
    expect(await screen.findByRole("heading", { name: "Ce lien ne marche plus" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Recevoir un nouveau lien" })).toBeEnabled();
  });

  it("l'équipe doit voir la demande : on le dit", async () => {
    verify.mockResolvedValue({ status: "team", company_slug: null, message: "Adresse vérifiée." });
    render(<VerifyLink token="jeton-equipe-0000000000000000" />);
    expect(await screen.findByText("Adresse vérifiée.")).toBeVisible();
  });
});
