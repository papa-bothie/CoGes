import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));

const config = vi.fn();
vi.mock("@/lib/signup/config", () => ({ signupConfig: () => config() }));

const CLOSED = {
  enabled: false,
  instant_with_email: false,
  support_whatsapp: "",
  resend_interval_seconds: 60,
};
const OPEN = { ...CLOSED, enabled: true, instant_with_email: true };

/** `notFound()` de Next lève une erreur reconnaissable à son `digest`. */
async function isNotFound(page: () => Promise<unknown>): Promise<boolean> {
  try {
    await page();
    return false;
  } catch (error) {
    return String((error as { digest?: string }).digest ?? "").includes("404");
  }
}

describe("interrupteur de l'inscription (ADR 0118)", () => {
  it("fermée : le formulaire et le lien n'existent pas (404)", async () => {
    config.mockResolvedValue(CLOSED);
    const { default: SignupPage } = await import("@/app/(auth)/inscription/page");
    const { default: Verification } = await import("@/app/(auth)/verification/[jeton]/page");
    expect(await isNotFound(() => SignupPage())).toBe(true);
    expect(
      await isNotFound(() => Verification({ params: Promise.resolve({ jeton: "x".repeat(43) }) })),
    ).toBe(true);
  });

  it("fermée : ni la vitrine ni la connexion ne montrent « Créer ma boutique »", async () => {
    config.mockResolvedValue(CLOSED);
    const { default: LoginPage } = await import("@/app/(auth)/login/page");
    const { unmount } = render(await LoginPage());
    expect(screen.queryByRole("link", { name: "Créer ma boutique" })).toBeNull();
    unmount();
    const { default: VitrinePage } = await import("@/app/(vitrine)/page");
    render(await VitrinePage());
    expect(screen.queryByRole("link", { name: "Créer ma boutique" })).toBeNull();
  });

  it("ouverte : le bouton paraît sur les deux, vers /inscription", async () => {
    config.mockResolvedValue(OPEN);
    const { default: LoginPage } = await import("@/app/(auth)/login/page");
    const { unmount } = render(await LoginPage());
    expect(screen.getByRole("link", { name: "Créer ma boutique" })).toHaveAttribute(
      "href",
      "/inscription",
    );
    unmount();
    const { default: VitrinePage } = await import("@/app/(vitrine)/page");
    render(await VitrinePage());
    for (const link of screen.getAllByRole("link", { name: "Créer ma boutique" })) {
      expect(link).toHaveAttribute("href", "/inscription");
    }
  });
});
