import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IDEMPOTENCY_HEADER, useIdempotencyKey } from "./idempotency";

describe("useIdempotencyKey", () => {
  it("garde la même clé d'un rendu à l'autre, tant qu'on ne la renouvelle pas", () => {
    const { result, rerender } = renderHook(() => useIdempotencyKey());
    const first = result.current.key;
    rerender();
    expect(result.current.key).toBe(first);
    expect(result.current.headers).toEqual({ [IDEMPOTENCY_HEADER]: first });
  });

  it("change de clé après un succès (renew)", () => {
    const { result } = renderHook(() => useIdempotencyKey());
    const first = result.current.key;
    act(() => result.current.renew());
    expect(result.current.key).not.toBe(first);
    expect(result.current.key).toMatch(/^[0-9a-f-]{36}$/);
  });
});
