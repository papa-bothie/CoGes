import { afterEach, describe, expect, it, vi } from "vitest";

import { splitAcrossDebts } from "./allocation";
import { createAuthFetch } from "./api/client";
import { logout, refreshSession, SESSION_MARKER } from "./auth/session";
import { tokenStore } from "./auth/token-store";
import { typedAmount } from "./payment-amount";

/** Constats de la revue sur le front (prompt 21, P2.25 ; ADR 0088). */

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  tokenStore.clear();
  document.cookie = `${SESSION_MARKER}=; Path=/; Max-Age=0`;
});

describe("(c) montant tapé", () => {
  it.each(["-500", "+500", "1.5", "1,5", "1e3", " 500"])("« %s » n'est pas un montant", (typed) => {
    expect(() => typedAmount(typed)).not.toThrow();
    expect(typedAmount(typed)).toBe(0n);
  });

  it("des chiffres seuls restent un montant", () => {
    expect(typedAmount("25000")).toBe(25000n);
  });
});

describe("(d) règlement réparti", () => {
  it("ignore les dettes sans solde", () => {
    const debts = [
      { id: "soldee", balance: "0.00" },
      { id: "negative", balance: "-100.00" },
      { id: "ouverte", balance: "5000.00" },
    ];
    expect(splitAcrossDebts("3000", debts)).toEqual({ ouverte: "3000" });
  });
});

describe("(e) session", () => {
  it("la déconnexion attend un rafraîchissement en cours", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        calls.push(input);
        if (input.endsWith("/refresh")) {
          await new Promise((resolve) => setTimeout(resolve, 20));
          return new Response(JSON.stringify({ access_token: "a1", expires_in: 900 }), {
            status: 200,
          });
        }
        return new Response(null, { status: 204 });
      }),
    );

    const pending = refreshSession();
    await logout();
    await pending;

    // Le rafraîchissement fini après la déconnexion aurait reposé un jeton.
    expect(calls).toEqual(["/api/v1/auth/refresh", "/api/v1/auth/logout"]);
    expect(tokenStore.get()).toBeNull();
  });

  it("un verrou d'onglet jamais rendu ne bloque pas le rafraîchissement", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("navigator", {
      locks: {
        request: (_name: string, options: { signal?: AbortSignal }) =>
          new Promise((_resolve, reject) => {
            options?.signal?.addEventListener("abort", () =>
              reject(new DOMException("aborted", "AbortError")),
            );
          }),
      },
    });

    const outcome = refreshSession();
    await vi.advanceTimersByTimeAsync(30_000);

    await expect(outcome).resolves.toBe("unavailable");
  });

  it("deux 401 décalés ne relancent pas une seconde rotation", async () => {
    let current: string | null = "ancien";
    const token = {
      fresh: () => current,
      get: () => current,
    };
    const refresh = vi.fn(async () => {
      current = "neuf";
      return "ok" as const;
    });
    const fetch = vi.fn(
      async (request: Request) =>
        new Response(null, {
          status: request.headers.get("Authorization") === "Bearer neuf" ? 200 : 401,
        }),
    );
    const authFetch = createAuthFetch({
      fetch,
      refresh,
      onExpired: vi.fn(),
      onSuspended: vi.fn(),
      token,
    });

    // La première requête rafraîchit ; la seconde, partie avec l'ancien jeton, revient
    // en 401 après coup : le jeton a déjà changé, inutile de le faire tourner encore.
    await authFetch(new Request("http://localhost/api/v1/sales"));
    current = "neuf";
    const late = createAuthFetch({
      fetch: async (request) => {
        if (request.headers.get("Authorization") === "Bearer ancien") {
          return new Response(null, { status: 401 });
        }
        return fetch(request);
      },
      refresh,
      onExpired: vi.fn(),
      onSuspended: vi.fn(),
      token: { fresh: () => "ancien", get: () => current },
    });
    const response = await late(new Request("http://localhost/api/v1/sales"));

    expect(response.status).toBe(200);
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});
