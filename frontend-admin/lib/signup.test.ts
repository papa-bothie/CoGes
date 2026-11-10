import { describe, expect, it } from "vitest";

import type { SignupRequestRead } from "@/lib/api/schema";

import {
  accessMessage,
  age,
  firstContactMessage,
  phoneDigits,
  requestState,
  whatsappLink,
} from "./signup";

const REQUEST: SignupRequestRead = {
  id: "00000000-0000-0000-0000-000000000001",
  shop_name: "Épicerie Awa",
  full_name: "Awa Ndiaye",
  phone: "+221770000000",
  email: null,
  path: "team",
  status: "pending",
  email_verified_at: null,
  reject_reason: null,
  team_note: null,
  created_at: "2026-11-10T08:00:00Z",
  path_changed_at: null,
  decided_at: null,
  decided_via: null,
  company_id: null,
  company_slug: null,
  legal_version: "2026-12-01",
  purged: false,
  known_accounts: [],
};

describe("demandes d'inscription (ADR 0118)", () => {
  it("l'accès envoyé sur WhatsApp donne le code et le lien, jamais un mot de passe", () => {
    const text = accessMessage("epicerie-awa", "https://coges.app/");
    expect(text).toContain("epicerie-awa");
    expect(text).toContain("https://coges.app/login?boutique=epicerie-awa");
    expect(text.toLowerCase()).not.toMatch(/mot de passe\s*:/);
  });

  it("le lien wa.me porte le numéro en chiffres et le message encodé", () => {
    expect(phoneDigits("+221 77 000 00 00")).toBe("221770000000");
    expect(whatsappLink("+221770000000", "Bonjour Awa")).toBe(
      "https://wa.me/221770000000?text=Bonjour%20Awa",
    );
    expect(firstContactMessage(REQUEST)).toContain("« Épicerie Awa »");
  });

  it("l'état de la demande est dit en mots", () => {
    expect(requestState(REQUEST).label).toBe("À traiter par l'équipe");
    expect(requestState({ ...REQUEST, path: "email" }).label).toBe("Lien e-mail en attente");
    expect(requestState({ ...REQUEST, status: "activated" }).label).toBe("Boutique ouverte");
    expect(requestState({ ...REQUEST, status: "rejected" }).tone).toBe("danger");
  });

  it("l'ancienneté se lit en heures puis en jours", () => {
    const now = new Date("2026-11-10T10:30:00Z");
    expect(age("2026-11-10T10:00:00Z", now)).toBe("moins d'1 h");
    expect(age("2026-11-10T08:00:00Z", now)).toBe("2 h");
    expect(age("2026-11-07T08:00:00Z", now)).toBe("3 j");
  });
});
