import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MerchantUserPage } from "@/lib/api/schema";

import { TYPING_DELAY_MS, UserDirectory } from "./user-directory";

const navigation = vi.hoisted(() => ({
  params: new URLSearchParams(),
  replace: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navigation.replace, push: navigation.push }),
  usePathname: () => "/users",
  useSearchParams: () => navigation.params,
}));

const PAGE: MerchantUserPage = {
  items: [
    {
      id: "u1",
      full_name: "Awa Ndiaye",
      email: "awa@boutique.example.com",
      company_id: "c1",
      company_name: "Boutique Awa",
      roles: ["gerant"],
      status: "active",
      last_login_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
    },
  ],
  page: 1,
  page_size: 20,
  total: 1,
};

type Get = (
  path: string,
  init?: unknown,
) => Promise<{ data: MerchantUserPage; response: Response }>;
const GET = vi.fn<Get>(async () => ({
  data: PAGE,
  response: new Response(null, { status: 200 }),
}));

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  api: { GET: (...args: unknown[]) => GET(...(args as [string])) },
}));

beforeEach(() => {
  navigation.params = new URLSearchParams();
  navigation.replace.mockClear();
  GET.mockClear();
});

describe("utilisateurs commerçants", () => {
  it("lit ses filtres dans l'adresse et les envoie au serveur", async () => {
    navigation.params = new URLSearchParams(
      "q=awa&role=gerant&status=active&company=c1&sort=name&page=2",
    );
    render(<UserDirectory />);
    await screen.findAllByText("Awa Ndiaye");
    expect(GET).toHaveBeenLastCalledWith("/api/v1/platform/users", {
      params: {
        query: {
          q: "awa",
          role: "gerant",
          status: "active",
          company_id: "c1",
          sort: "name",
          page: 2,
          page_size: 20,
        },
      },
    });
    expect(screen.getByRole("link", { name: "Gérant" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("link", { name: /Boutique Awa ×/ })).toHaveAttribute(
      "href",
      "/users?q=awa&role=gerant&status=active&sort=name",
    );
  });

  it("une puce change l'adresse et revient à la page 1", async () => {
    navigation.params = new URLSearchParams("page=3");
    render(<UserDirectory />);
    await screen.findAllByText("Awa Ndiaye");
    expect(screen.getByRole("link", { name: "Désactivés" })).toHaveAttribute(
      "href",
      "/users?status=deactivated",
    );
  });

  it("la saisie part dans l'adresse après 300 ms, pas avant", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<UserDirectory />);
    await user.type(screen.getByLabelText("Nom, e-mail ou entreprise"), "awa");
    expect(navigation.replace).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(TYPING_DELAY_MS);
    });
    expect(navigation.replace).toHaveBeenLastCalledWith("/users?q=awa");
    vi.useRealTimers();
  });

  it("le tri se fait par l'en-tête, annoncé par aria-sort", async () => {
    navigation.params = new URLSearchParams("sort=name");
    render(<UserDirectory />);
    await screen.findAllByText("Awa Ndiaye");
    const name = screen.getByRole("columnheader", { name: /Nom/ });
    expect(name).toHaveAttribute("aria-sort", "ascending");
    expect(within(name).getByRole("link")).toHaveAttribute("href", "/users?sort=-name");
    expect(screen.getByRole("columnheader", { name: /Dernière connexion/ })).toHaveAttribute(
      "aria-sort",
      "none",
    );
  });

  it("donne la date exacte de la dernière connexion à côté du relatif", async () => {
    render(<UserDirectory />);
    const [time] = await screen.findAllByText(/il y a 3 jours/);
    expect(time!.closest("time")).toHaveAttribute(
      "title",
      expect.stringMatching(/\d\d\/\d\d\/\d{4}/),
    );
  });

  it("montre un tableau et des cartes (les cartes sous 768 px)", async () => {
    render(<UserDirectory />);
    await screen.findAllByText("Awa Ndiaye");
    expect(screen.getByRole("table").parentElement).toHaveClass("hidden", "md:block");
    expect(screen.getByRole("list", { name: "Comptes" })).toHaveClass("md:hidden");
  });

  it("un résultat vide dit quoi faire", async () => {
    GET.mockResolvedValueOnce({
      data: { items: [], page: 1, page_size: 20, total: 0 },
      response: new Response(null, { status: 200 }),
    });
    navigation.params = new URLSearchParams("q=personne");
    render(<UserDirectory />);
    expect(await screen.findByText("Aucun compte ne correspond.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Tout afficher" })).toHaveAttribute("href", "/users");
  });

  it("rappelle que la liste est en lecture seule", async () => {
    render(<UserDirectory />);
    expect(
      screen.getByText("Lecture seule — les comptes des commerçants sont gérés par leur gérant."),
    ).toBeVisible();
    await screen.findAllByText("Awa Ndiaye");
    expect(screen.queryByRole("button", { name: /Désactiver|Modifier/ })).toBeNull();
  });
});
