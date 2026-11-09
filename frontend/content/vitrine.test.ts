import { describe, expect, it } from "vitest";

import { vitrine, whatsappLink } from "./vitrine";

/**
 * Contenu fourni par le propriétaire (prompt 37, ADR 0115). Le numéro factice livré avec le
 * lot fait échouer ce test : la page ne part jamais en production avec un faux contact.
 */
describe("vitrine : contenu du propriétaire", () => {
  it("le numéro WhatsApp est réel (format international, chiffres seuls)", () => {
    expect(vitrine.whatsappNumber).toMatch(/^[1-9]\d{7,14}$/);
    expect(
      vitrine.whatsappNumber,
      "numéro factice : à remplacer dans content/vitrine.ts",
    ).not.toMatch(/^(221)?0+$|^(\d)\1+$/);
  });

  it("horaires et message prérempli sont renseignés", () => {
    expect(vitrine.supportHours.trim()).not.toBe("");
    expect(vitrine.whatsappMessage.trim()).not.toBe("");
  });

  it("l'adresse publique est le domaine nu en https", () => {
    expect(vitrine.siteUrl).toMatch(/^https:\/\/[a-z0-9.-]+$/);
    expect(vitrine.siteUrl).not.toContain("www.");
  });
});

describe("whatsappLink", () => {
  it("ouvre wa.me avec le numéro et le message prérempli encodé", () => {
    const url = new URL(whatsappLink());
    expect(url.origin).toBe("https://wa.me");
    expect(url.pathname).toBe(`/${vitrine.whatsappNumber}`);
    expect(url.searchParams.get("text")).toBe(vitrine.whatsappMessage);
    expect(whatsappLink()).not.toContain("+");
  });
});
