import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SignupFlow, phoneDigits, validate, withCountryCode } from "./signup-flow";

const create = vi.fn();
const resend = vi.fn();
const contact = vi.fn();
vi.mock("@/lib/signup/api", async (original) => ({
  ...(await original<typeof import("@/lib/signup/api")>()),
  createSignupRequest: (...args: unknown[]) => create(...args),
  resendSignupLink: (...args: unknown[]) => resend(...args),
  contactSignupTeam: (...args: unknown[]) => contact(...args),
}));

const SECRET = ["mon", "mot", "de", "passe", "2026"].join("-");
const VALID = {
  shop_name: "Épicerie Awa",
  full_name: "Awa Ndiaye",
  phone: "77 000 00 00",
  email: "",
  password: SECRET,
  confirm: SECRET,
};

function flow(instant = true) {
  return render(
    <SignupFlow
      instantWithEmail={instant}
      whatsapp="221781811756"
      supportHours="Du lundi au samedi, de 9 h à 19 h"
      resendSeconds={60}
    />,
  );
}

async function fill(user: ReturnType<typeof userEvent.setup>, email = "") {
  await user.type(screen.getByLabelText("Nom de la boutique"), VALID.shop_name);
  await user.type(screen.getByLabelText("Votre nom"), VALID.full_name);
  await user.type(screen.getByLabelText("Numéro de téléphone"), VALID.phone);
  if (email) await user.type(screen.getByLabelText(/^E-mail/), email);
  await user.type(screen.getByLabelText("Mot de passe", { exact: true }), VALID.password);
  await user.type(screen.getByLabelText("Retapez le mot de passe"), VALID.confirm);
}

beforeEach(() => {
  create.mockReset();
  resend.mockReset();
  contact.mockReset();
});

describe("numéro de téléphone (ADR 0118)", () => {
  it.each(["77 000 00 00", "+221 77 000 00 00", "00221770000000", "770000000"])(
    "« %s » donne les mêmes chiffres",
    (typed) => {
      expect(phoneDigits(typed)).toBe("770000000");
    },
  );

  it("un numéro sans indicatif part avec +221, un numéro qui en a un part tel quel", () => {
    expect(withCountryCode("77 000 00 00")).toBe("+221 77 000 00 00");
    expect(withCountryCode("+33 6 12 34 56 78")).toBe("+33 6 12 34 56 78");
    expect(withCountryCode("00221 77 000 00 00")).toBe("00221 77 000 00 00");
  });
});

describe("contrôles du formulaire", () => {
  it("l'e-mail est facultatif, mais une adresse fausse est refusée", () => {
    expect(validate(VALID)).toEqual({});
    expect(validate({ ...VALID, email: "awa@" })).toEqual({
      email: "Cette adresse e-mail n'est pas valide.",
    });
  });

  it("mot de passe trop court, puis différent", () => {
    expect(validate({ ...VALID, password: "court", confirm: "court" }).password).toBe(
      "12 caractères au moins.",
    );
    expect(validate({ ...VALID, confirm: "autre-chose-2026" }).confirm).toBe(
      "Les deux mots de passe ne sont pas identiques.",
    );
  });

  it("numéro manquant ou illisible", () => {
    expect(validate({ ...VALID, phone: "" }).phone).toBe("Ce champ est obligatoire.");
    expect(validate({ ...VALID, phone: "12" }).phone).toBe(
      "Ce numéro de téléphone n'est pas valide.",
    );
  });
});

describe("« Créer ma boutique »", () => {
  it("le bouton reste inactif tant que la case des conditions n'est pas cochée", async () => {
    const user = userEvent.setup();
    flow();
    const button = screen.getByRole("button", { name: "Créer ma boutique" });
    expect(button).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /J'ai lu et j'accepte/ }));
    expect(button).toBeEnabled();
  });

  it("le mot de passe se montre, et la règle est visible avant toute erreur", async () => {
    const user = userEvent.setup();
    flow();
    expect(screen.getByText(/12 caractères au moins\. Une phrase courte/)).toBeInTheDocument();
    const field = screen.getByLabelText("Mot de passe", { exact: true });
    await user.type(field, "secret");
    await user.click(screen.getAllByRole("button", { name: "Afficher le mot de passe" })[0]!);
    expect(field).toHaveAttribute("type", "text");
  });

  it("avec un e-mail : l'écran « Vérifiez votre e-mail », adresse masquée", async () => {
    const user = userEvent.setup();
    create.mockResolvedValue({ path: "email", message: "…" });
    flow();
    await fill(user, "awa.ndiaye@example.com");
    await user.click(screen.getByRole("checkbox", { name: /J'ai lu et j'accepte/ }));
    await user.click(screen.getByRole("button", { name: "Créer ma boutique" }));
    expect(await screen.findByRole("heading", { name: "Vérifiez votre e-mail" })).toHaveFocus();
    expect(screen.getByText(/a•+@example\.com/)).toBeInTheDocument();
    expect(screen.queryByText("awa.ndiaye@example.com")).toBeNull();
    // Renvoi : attendre le délai affiché.
    expect(screen.getByRole("button", { name: /Renvoyer le lien \(dans 60 s\)/ })).toBeDisabled();
    const body = create.mock.calls[0]![0];
    expect(body).toMatchObject({
      phone: "+221 77 000 00 00",
      email: "awa.ndiaye@example.com",
      accept_legal: true,
      website: "",
    });
    expect(body).not.toHaveProperty("confirm");
  });

  it("« Je n'ai pas reçu l'e-mail » mène à l'écran de l'équipe", async () => {
    const user = userEvent.setup();
    create.mockResolvedValue({ path: "email", message: "…" });
    contact.mockResolvedValue({ message: "…" });
    flow();
    await fill(user, "awa@example.com");
    await user.click(screen.getByRole("checkbox", { name: /J'ai lu et j'accepte/ }));
    await user.click(screen.getByRole("button", { name: "Créer ma boutique" }));
    await user.click(await screen.findByRole("button", { name: /Je n'ai pas reçu l'e-mail/ }));
    expect(contact).toHaveBeenCalledWith("awa@example.com");
    expect(await screen.findByRole("heading", { name: "Demande reçue" })).toBeInTheDocument();
  });

  it("sans e-mail : « Demande reçue », horaires, WhatsApp et trois étapes", async () => {
    const user = userEvent.setup();
    create.mockResolvedValue({ path: "team", message: "…" });
    flow(false);
    expect(screen.getByText(/nous ouvrons votre boutique avec vous sur WhatsApp/)).toBeVisible();
    await fill(user);
    await user.click(screen.getByRole("checkbox", { name: /J'ai lu et j'accepte/ }));
    await user.click(screen.getByRole("button", { name: "Créer ma boutique" }));
    expect(await screen.findByRole("heading", { name: "Demande reçue" })).toHaveFocus();
    expect(screen.getByText("Du lundi au samedi, de 9 h à 19 h")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Nous écrire sur WhatsApp/ })).toHaveAttribute(
      "href",
      "https://wa.me/221781811756",
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it("une erreur du serveur s'annonce, le formulaire reste rempli", async () => {
    const user = userEvent.setup();
    create.mockRejectedValue(new Error("Trop de demandes."));
    flow();
    await fill(user);
    await user.click(screen.getByRole("checkbox", { name: /J'ai lu et j'accepte/ }));
    await user.click(screen.getByRole("button", { name: "Créer ma boutique" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByLabelText("Nom de la boutique")).toHaveValue("Épicerie Awa");
  });
});
