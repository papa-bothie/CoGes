import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlatformMe, ProfileRead, TeamList } from "@/lib/api/schema";

import { TeamView } from "./team-view";

const state = vi.hoisted(() => ({ me: null as unknown, params: new URLSearchParams() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/team",
  useSearchParams: () => state.params,
}));
vi.mock("@/components/admin-shell", () => ({ useMe: () => state.me }));

const TEAM: TeamList = {
  members: [
    {
      id: "me",
      email: "aissatou@coges.example.com",
      display_name: "Aïssatou Diop",
      role: "administrator",
      is_active: true,
      last_login_at: null,
      created_at: "2026-10-01T10:00:00Z",
      is_me: true,
    },
    {
      id: "moussa",
      email: "moussa@coges.example.com",
      display_name: "Moussa Badji",
      role: "support",
      is_active: true,
      last_login_at: null,
      created_at: "2026-10-02T10:00:00Z",
      is_me: false,
    },
  ],
  invitations: [
    {
      id: "inv",
      email: "fatou@coges.example.com",
      display_name: "Fatou Sow",
      role: "support",
      created_at: "2026-10-24T10:00:00Z",
      expires_at: "2026-10-27T10:00:00Z",
      invited_by_name: "Aïssatou Diop",
    },
  ],
};
const PROFILES: ProfileRead[] = [
  {
    role: "administrator",
    label: "Administrateur",
    description: "Gère l'équipe.",
    capabilities: [{ key: "POST /team/invitations", label: "Inviter un collègue" }],
  },
  {
    role: "support",
    label: "Support",
    description: "Consulte.",
    capabilities: [{ key: "GET /team", label: "Voir l'équipe" }],
  },
];

const PATCH = vi.fn(async () => ({ data: {}, response: new Response(null, { status: 200 }) }));
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  api: {
    GET: async (path: string) => ({
      data: path === "/api/v1/platform/roles" ? PROFILES : TEAM,
      response: new Response(null, { status: 200 }),
    }),
    PATCH: (...args: unknown[]) => PATCH(...(args as [])),
  },
}));

const ME = (role: string): PlatformMe => ({
  id: "me",
  email: "aissatou@coges.example.com",
  display_name: "Aïssatou Diop",
  role: role as PlatformMe["role"],
});

beforeEach(() => {
  state.params = new URLSearchParams();
  PATCH.mockClear();
});

function rowOf(name: string): HTMLElement {
  return screen.getByRole("row", { name: new RegExp(name) });
}

describe("équipe", () => {
  it("le profil Support voit la liste sans aucun bouton d'action", async () => {
    state.me = ME("support");
    render(<TeamView />);
    await screen.findAllByText("Moussa Badji");
    expect(
      screen.queryByRole("button", {
        name: /Inviter|Changer le profil|Suspendre|Renvoyer|Annuler/,
      }),
    ).toBeNull();
    expect(screen.queryByRole("link", { name: /Historique/ })).toBeNull();
    // Le panneau des profils, lui, est lu par tous.
    expect(screen.getByText("Voir l'équipe")).toBeVisible();
  });

  it("sa propre ligne n'a ni « Suspendre » ni « Changer le profil », avec la raison", async () => {
    state.me = ME("administrator");
    render(<TeamView />);
    await screen.findAllByText("Moussa Badji");
    const own = rowOf("Aïssatou Diop");
    expect(within(own).queryByRole("button")).toBeNull();
    expect(
      within(own).getByText(/un autre administrateur peut changer votre profil/),
    ).toBeVisible();
    expect(within(rowOf("Moussa Badji")).getByRole("button", { name: /Suspendre/ })).toBeVisible();
  });

  it("une invitation se renvoie ou s'annule, et dit jusqu'à quand le lien vaut", async () => {
    state.me = ME("administrator");
    render(<TeamView />);
    await screen.findAllByText("Fatou Sow");
    const row = rowOf("Fatou Sow");
    expect(within(row).getByText("Invité")).toBeVisible();
    expect(within(row).getByText(/Lien valable jusqu'au/)).toBeVisible();
    expect(within(row).getByRole("button", { name: /Renvoyer/ })).toBeVisible();
    expect(within(row).getByRole("button", { name: /Annuler/ })).toBeVisible();
  });

  it("changer le profil : un clic, une confirmation qui nomme la cible", async () => {
    state.me = ME("administrator");
    render(<TeamView />);
    await screen.findAllByText("Moussa Badji");
    await userEvent.click(
      within(rowOf("Moussa Badji")).getByRole("button", { name: /Changer le profil/ }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Passer Moussa B. en Administrateur" }),
    );
    expect(PATCH).toHaveBeenCalledWith("/api/v1/platform/team/{user_id}", {
      params: { path: { user_id: "moussa" } },
      body: { role: "administrator" },
    });
    expect(await screen.findByText(/Moussa B\. est maintenant Administrateur/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Voir dans le journal" })).toHaveAttribute(
      "href",
      "/audit?entity=moussa",
    );
  });

  it("le filtre « Invités » ne garde que les invitations", async () => {
    state.me = ME("administrator");
    state.params = new URLSearchParams("status=invited");
    render(<TeamView />);
    await screen.findAllByText("Fatou Sow");
    expect(screen.queryAllByText("Moussa Badji")).toHaveLength(0);
  });
});
