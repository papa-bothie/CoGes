import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { draftKey, writeDraft } from "@/lib/drafts";

import { DRAFT_DELAY_MS, hasUnsentDrafts, useDraft } from "./use-draft";

const AWA = { companyId: "c1", userId: "u1" };
let current = AWA;

vi.mock("@/hooks/use-me", () => ({
  useMe: () => ({ data: { company: { id: current.companyId }, user: { id: current.userId } } }),
}));
const KEY = draftKey(AWA, "test-form");
const SPEC = { formId: "test-form", version: 1, fields: ["label", "amount"] } as const;

function Form() {
  const [label, setLabel] = useState("");
  const [amount, setAmount] = useState("");
  const [password, setPassword] = useState("");
  const draft = useDraft(SPEC, { label, amount, password }, (fields) => {
    if (typeof fields.label === "string") setLabel(fields.label);
    if (typeof fields.amount === "string") setAmount(fields.amount);
  });
  return (
    <form>
      {draft.restored && <p role="status">Brouillon retrouvé</p>}
      <input aria-label="Libellé" value={label} onChange={(e) => setLabel(e.target.value)} />
      <input aria-label="Montant" value={amount} onChange={(e) => setAmount(e.target.value)} />
      <input
        aria-label="Mot de passe"
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <button type="button" onClick={draft.clear}>
        Envoyer
      </button>
    </form>
  );
}

describe("useDraft (ADR 0101)", () => {
  beforeEach(() => {
    current = AWA;
  });
  afterEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it("écrit après un court délai, pas à chaque touche, et jamais le mot de passe", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<Form />);
    await user.type(screen.getByLabelText("Libellé"), "Riz");
    await user.type(screen.getByLabelText("Mot de passe"), "piège-secret-123");
    expect(window.localStorage.getItem(KEY)).toBeNull();
    act(() => vi.advanceTimersByTime(DRAFT_DELAY_MS + 10));
    expect(JSON.parse(window.localStorage.getItem(KEY)!).fields).toEqual({
      label: "Riz",
      amount: "",
    });
    expect(JSON.stringify({ ...window.localStorage })).not.toContain("piège-secret-123");
    expect(hasUnsentDrafts()).toBe(true);
  });

  it("écrit tout de suite quand la page est cachée", async () => {
    const user = userEvent.setup();
    render(<Form />);
    await user.type(screen.getByLabelText("Montant"), "500");
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    expect(JSON.parse(window.localStorage.getItem(KEY)!).fields.amount).toBe("500");
  });

  it("retrouve la saisie à l'ouverture, avec le bandeau", async () => {
    writeDraft(KEY, 1, { label: "Sucre", amount: "750" }, SPEC.fields);
    render(<Form />);
    expect(await screen.findByText("Brouillon retrouvé")).toBeInTheDocument();
    expect(screen.getByLabelText("Libellé")).toHaveValue("Sucre");
    expect(screen.getByLabelText("Montant")).toHaveValue("750");
  });

  it("rien pour une autre personne sur le même navigateur", () => {
    writeDraft(KEY, 1, { label: "Sucre", amount: "750" }, SPEC.fields);
    current = { companyId: "c1", userId: "u2" };
    render(<Form />);
    expect(screen.getByLabelText("Libellé")).toHaveValue("");
    expect(screen.queryByText("Brouillon retrouvé")).toBeNull();
  });

  it("l'envoi efface le brouillon et ne le réécrit pas", async () => {
    writeDraft(KEY, 1, { label: "Sucre", amount: "750" }, SPEC.fields);
    const view = render(<Form />);
    await screen.findByText("Brouillon retrouvé");
    await userEvent.click(screen.getByRole("button", { name: "Envoyer" }));
    expect(window.localStorage.getItem(KEY)).toBeNull();
    await new Promise((resolve) => setTimeout(resolve, DRAFT_DELAY_MS + 50));
    view.unmount();
    expect(window.localStorage.getItem(KEY)).toBeNull();
    expect(screen.queryByText("Brouillon retrouvé")).toBeNull();
  });

  it("suit l'onglet voisin sans boucle", async () => {
    render(<Form />);
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    act(() => {
      writeDraft(KEY, 1, { label: "Huile", amount: "1200" }, SPEC.fields);
      window.dispatchEvent(
        new StorageEvent("storage", { key: KEY, newValue: window.localStorage.getItem(KEY) }),
      );
    });
    expect(screen.getByLabelText("Libellé")).toHaveValue("Huile");
    setItem.mockClear();
    await new Promise((resolve) => setTimeout(resolve, DRAFT_DELAY_MS + 50));
    // La valeur reçue n'est pas réécrite : pas de ping-pong entre onglets.
    expect(setItem).not.toHaveBeenCalled();
  });
});
