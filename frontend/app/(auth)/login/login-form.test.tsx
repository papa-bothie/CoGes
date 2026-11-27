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

describe("connexion : boutique en pause (ADR 0089, 0133)", () => {
  beforeEach(() => {
    login.mockReset();
    search = "";
  });

  it("montre la boutique en pause et WhatsApp pour payer, pas une erreur d'identifiants", async () => {
    login.mockRejectedValue(new ApiError(403, "company_suspended", "suspendu", {}));
    render(<LoginForm />);
    await submit();
    const paused = await screen.findByRole("alert");
    expect(paused).toHaveTextContent(labels.renewal.pausedTitle);
    expect(paused).toHaveTextContent("Vos ventes, votre stock et vos clients sont gardés");
    expect(screen.queryByText(labels.login.invalid)).toBeNull();
    const link = screen.getByRole("link", { name: labels.renewal.pausedWhatsapp });
    const url = new URL(link.getAttribute("href") ?? "");
    expect(url.hostname).toBe("wa.me");
    expect(url.searchParams.get("text")).toContain("rouvrir ma boutique CoGes");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("explique la déconnexion forcée en cours de session", () => {
    search = "reason=suspended";
    render(<LoginForm />);
    expect(screen.getByRole("status")).toHaveTextContent(labels.renewal.pausedTitle);
  });
});
