import type { Query } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { ApiError, networkError } from "@/lib/api/errors";
import { retryDelay, shouldRetry } from "@/lib/api/query";

import { connectionState } from "./connection-banner";

const query = (state: Partial<Query["state"]>) => ({ state }) as unknown as Query;

describe("bandeau de connexion (ADR 0085)", () => {
  it("annonce les nouveaux essais d'une lecture coupée", () => {
    expect(
      connectionState([query({ fetchStatus: "fetching", fetchFailureReason: networkError() })]),
    ).toBe("retrying");
    expect(
      connectionState([
        query({ fetchStatus: "fetching", fetchFailureReason: new ApiError(503, "x", "y") }),
      ]),
    ).toBe("retrying");
  });

  it("passe en manuel quand les essais sont épuisés", () => {
    expect(
      connectionState([query({ status: "error", fetchStatus: "idle", error: networkError() })]),
    ).toBe("lost");
  });

  it("se tait pour une erreur qui n'est pas une coupure", () => {
    expect(
      connectionState([
        query({ status: "error", fetchStatus: "idle", error: new ApiError(404, "not_found", "") }),
        query({
          status: "error",
          fetchStatus: "idle",
          error: new ApiError(500, "server_error", ""),
        }),
        query({ status: "success", fetchStatus: "idle" }),
      ]),
    ).toBe("ok");
  });

  it("réessaie une lecture coupée 3 fois, à 2, 4 puis 8 s", () => {
    expect([0, 1, 2].map(retryDelay)).toEqual([2000, 4000, 8000]);
    expect(shouldRetry(2, networkError())).toBe(true);
    expect(shouldRetry(3, networkError())).toBe(false);
    expect(shouldRetry(0, new ApiError(422, "validation_failed", ""))).toBe(false);
  });
});
