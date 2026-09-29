// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import type { RefreshOutcome } from "@/lib/auth/session";

import { createAuthFetch } from "./client";

function tokenHolder(initial: string | null) {
  let current = initial;
  return {
    fresh: () => current,
    get: () => current,
    set: (value: string | null) => {
      current = value;
    },
  };
}

function setup(options: { token: string | null; refreshTo?: RefreshOutcome; newToken?: string }) {
  const token = tokenHolder(options.token);
  const seen: (string | null)[] = [];
  const responses: number[] = [];
  const fetch = vi.fn(async (request: Request) => {
    const auth = request.headers.get("Authorization");
    seen.push(auth);
    const status = auth === `Bearer ${options.newToken ?? "neuf"}` ? 200 : 401;
    responses.push(status);
    return new Response(JSON.stringify({ body: await request.text() }), { status });
  });
  const refresh = vi.fn(async () => {
    await new Promise((resolve) => setTimeout(resolve, 5));
    if ((options.refreshTo ?? "ok") === "ok") token.set(options.newToken ?? "neuf");
    return options.refreshTo ?? "ok";
  });
  const onExpired = vi.fn();
  const authFetch = createAuthFetch({ fetch, refresh, onExpired, token });
  return { authFetch, fetch, refresh, onExpired, seen, responses };
}

const url = "http://localhost/api/v1/sales";

describe("authFetch", () => {
  it("ajoute le jeton d'accès en mémoire", async () => {
    const { authFetch, seen } = setup({ token: "neuf" });
    const response = await authFetch(new Request(url));
    expect(response.status).toBe(200);
    expect(seen).toEqual(["Bearer neuf"]);
  });

  it("sur 401 : un rafraîchissement, puis rejoue la requête avec son corps", async () => {
    const { authFetch, refresh, seen } = setup({ token: "périmé" });
    const response = await authFetch(new Request(url, { method: "POST", body: '{"a":1}' }));
    expect(response.status).toBe(200);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(seen).toEqual(["Bearer périmé", "Bearer neuf"]);
    expect(await response.json()).toEqual({ body: '{"a":1}' });
  });

  it("sans jeton (page rechargée) : rafraîchit avant d'envoyer", async () => {
    const { authFetch, refresh, seen } = setup({ token: null });
    const response = await authFetch(new Request(url));
    expect(response.status).toBe(200);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(seen).toEqual(["Bearer neuf"]);
  });

  it("refresh refusé : session expirée, aucune requête envoyée sans jeton", async () => {
    const { authFetch, onExpired, fetch } = setup({ token: null, refreshTo: "unauthenticated" });
    const response = await authFetch(new Request(url));
    expect(response.status).toBe(401);
    expect(onExpired).toHaveBeenCalledTimes(1);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("serveur injoignable pendant le refresh : pas de déconnexion", async () => {
    const { authFetch, onExpired } = setup({ token: "périmé", refreshTo: "unavailable" });
    const response = await authFetch(new Request(url));
    expect(response.status).toBe(401);
    expect(onExpired).not.toHaveBeenCalled();
  });

  it("ne rafraîchit jamais sur les routes de session", async () => {
    const { authFetch, refresh } = setup({ token: null });
    const response = await authFetch(
      new Request("http://localhost/api/v1/auth/login", { method: "POST" }),
    );
    expect(response.status).toBe(401);
    expect(refresh).not.toHaveBeenCalled();
  });
});
