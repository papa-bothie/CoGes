import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearDraftsOf,
  clearOwnDrafts,
  DRAFT_TTL_MS,
  draftKey,
  purgeExpiredDrafts,
  readDraft,
  setDraftOwner,
  writeDraft,
} from "./drafts";

const AWA = { companyId: "c1", userId: "u1" };
const MODOU = { companyId: "c1", userId: "u2" };
const OTHER_SHOP = { companyId: "c2", userId: "u1" };

describe("brouillons (ADR 0101)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    setDraftOwner(null);
  });

  it("une clé par entreprise, par personne et par objet", () => {
    expect(draftKey(AWA, "expense")).toBe("coges:draft:v1:c1:u1:expense");
    expect(draftKey(AWA, "product", "p9")).toBe("coges:draft:v1:c1:u1:product:p9");
    writeDraft(draftKey(AWA, "expense"), 1, { amount: "500" }, ["amount"]);
    expect(readDraft(draftKey(MODOU, "expense"), 1, ["amount"])).toBeNull();
    expect(readDraft(draftKey(OTHER_SHOP, "expense"), 1, ["amount"])).toBeNull();
    expect(readDraft(draftKey(AWA, "expense"), 1, ["amount"])?.fields).toEqual({ amount: "500" });
  });

  it("n'écrit que la liste blanche : jamais un mot de passe", () => {
    const key = draftKey(AWA, "person");
    writeDraft(key, 1, { name: "Awa", password: "piège-secret-123" }, ["name"]);
    const everything = JSON.stringify({ ...window.localStorage });
    expect(everything).not.toContain("piège-secret-123");
    expect(readDraft(key, 1, ["name", "password"])?.fields).toEqual({ name: "Awa" });
  });

  it("ignore et retire une version inconnue", () => {
    const key = draftKey(AWA, "expense");
    writeDraft(key, 1, { amount: "500" }, ["amount"]);
    expect(readDraft(key, 2, ["amount"])).toBeNull();
    expect(window.localStorage.getItem(key)).toBeNull();
  });

  it("efface un brouillon de plus de 24 heures", () => {
    const key = draftKey(AWA, "expense");
    writeDraft(key, 1, { amount: "500" }, ["amount"], 1_000);
    expect(readDraft(key, 1, ["amount"], 1_000 + DRAFT_TTL_MS - 1)).not.toBeNull();
    expect(readDraft(key, 1, ["amount"], 1_000 + DRAFT_TTL_MS + 1)).toBeNull();
    writeDraft(key, 1, { amount: "500" }, ["amount"], 1_000);
    purgeExpiredDrafts(1_000 + DRAFT_TTL_MS + 1);
    expect(window.localStorage.getItem(key)).toBeNull();
  });

  it("la déconnexion efface tous les brouillons de la personne, et seulement les siens", () => {
    writeDraft(draftKey(AWA, "expense"), 1, { amount: "1" }, ["amount"]);
    writeDraft(draftKey(AWA, "product", "p1"), 1, { name: "Riz" }, ["name"]);
    writeDraft(draftKey(MODOU, "expense"), 1, { amount: "2" }, ["amount"]);
    window.localStorage.setItem("coges-admin:theme", "dark");
    setDraftOwner(AWA);
    clearOwnDrafts();
    expect(window.localStorage.getItem(draftKey(AWA, "expense"))).toBeNull();
    expect(window.localStorage.getItem(draftKey(AWA, "product", "p1"))).toBeNull();
    expect(window.localStorage.getItem(draftKey(MODOU, "expense"))).not.toBeNull();
    expect(window.localStorage.getItem("coges-admin:theme")).toBe("dark");
    clearDraftsOf(MODOU);
    expect(window.localStorage.getItem(draftKey(MODOU, "expense"))).toBeNull();
  });

  it("un stockage en panne ne casse rien", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(() => writeDraft(draftKey(AWA, "x"), 1, { a: 1 }, ["a"])).not.toThrow();
    expect(readDraft(draftKey(AWA, "x"), 1, ["a"])).toBeNull();
    expect(() => purgeExpiredDrafts()).not.toThrow();
  });
});
