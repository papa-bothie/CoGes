import { describe, expect, it, vi } from "vitest";

import { ApiError } from "./errors";
import { makeQueryClient, refreshIdentityOnDenial } from "./query";

describe("droit retiré par le gérant (ADR 0099)", () => {
  it("un 403 permission_denied relit l'identité", () => {
    const client = makeQueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
    refreshIdentityOnDenial(client, new ApiError(403, "permission_denied", "Refusé."));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["auth", "me"] });
  });

  it("aucune autre erreur ne la relit", () => {
    const client = makeQueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
    refreshIdentityOnDenial(client, new ApiError(403, "company_suspended", "Suspendue."));
    refreshIdentityOnDenial(client, new ApiError(409, "insufficient_stock", "Stock."));
    refreshIdentityOnDenial(client, new Error("réseau"));
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("le cache des lectures s'en charge tout seul", async () => {
    const client = makeQueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
    await client
      .fetchQuery({
        queryKey: ["debts"],
        queryFn: () => Promise.reject(new ApiError(403, "permission_denied", "Refusé.")),
        retry: false,
      })
      .catch(() => undefined);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["auth", "me"] });
  });
});
