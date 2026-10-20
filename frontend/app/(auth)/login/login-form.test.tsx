import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { labels } from "@/lib/labels";

const login = vi.fn();
let search = "";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock("@/lib/auth/session", async (original) => ({
  ...(await original<typeof import("@/lib/auth/session")>()),
  login: (...args: unknown[]) => login(...args),
}));

const { LoginForm } = await import("./login-form");

async function submit(): Promise<void> {
  await userEvent.type(screen.getByLabelText(labels.login.companySlug), "boutique-diallo");
  await userEvent.type(screen.getByLabelText(labels.login.identifier), "awa@example.com");
  await userEvent.type(screen.getByLabelText(labels.login.password), "mot-de-passe");
  await userEvent.click(screen.getByRole("button", { name: labels.login.submit }));
}

describe("connexion : entreprise suspendue (ADR 0089)", () => {
  beforeEach(() => {
    login.mockReset();
    search = "";
  });

  it("dit que l'accès est suspendu, pas que les identifiants sont faux", async () => {
    login.mockRejectedValue(new ApiError(403, "company_suspended", "suspendu", {}));
    render(<LoginForm />);
    await submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(labels.login.suspended);
    expect(screen.queryByText(labels.login.invalid)).toBeNull();
  });

  it("explique la déconnexion forcée en cours de session", () => {
    search = "reason=suspended";
    render(<LoginForm />);
    expect(screen.getByRole("status")).toHaveTextContent(labels.login.suspended);
  });
});
