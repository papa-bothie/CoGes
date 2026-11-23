import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Me } from "@/lib/api/schema";
import { renderWithClient } from "@/test/render";

import { SettingsMenu } from "./settings-menu";

vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({
  api: { GET: vi.fn(async () => ({ public_key: null })) },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));
vi.mock("@/lib/auth/session", () => ({ logout: vi.fn(), loginUrl: () => "/login" }));
vi.mock("@/components/pwa/install-invite", () => ({
  useInstall: () => ({ installed: false, canPrompt: false, iosHelp: false }),
}));

/** Droits des trois rôles par défaut, réduits à ce que le menu lit (ADR 0099). */
const ROLES: Record<string, string[]> = {
  Gérant: ["company:update", "users:read", "analytics:read", "notifications:read"],
  Vendeur: ["sales:create", "notifications:read"],
  Comptable: ["analytics:read", "audit_logs:read", "notifications:read"],
};

function me(role: string): Me {
  return {
    user: { full_name: "Awa Ndiaye" },
    roles: [{ name: role, description: role }],
    permissions: ROLES[role],
  } as unknown as Me;
}

describe("menu du compte (prompt 40, lot A, ADR 0130)", () => {
  it.each(Object.keys(ROLES))(
    "%s : ni « Conditions » ni « Confidentialité », le reste est là",
    async (role) => {
      const user = userEvent.setup();
      renderWithClient(<SettingsMenu me={me(role)} />);
      await user.click(screen.getByRole("button", { name: /Réglages|compte/i }));
      const menu = await screen.findByRole("menu");
      expect(menu).toHaveTextContent("Awa Ndiaye");
      expect(screen.getByRole("menuitem", { name: /mot de passe/i })).toBeInTheDocument();
      expect(screen.getByRole("menuitem", { name: /Se déconnecter/ })).toBeInTheDocument();
      expect(screen.queryByRole("menuitem", { name: /Conditions/ })).toBeNull();
      expect(screen.queryByRole("menuitem", { name: /Confidentialité/ })).toBeNull();
      expect(menu.querySelector('a[href="/conditions"], a[href="/confidentialite"]')).toBeNull();
    },
  );
});
