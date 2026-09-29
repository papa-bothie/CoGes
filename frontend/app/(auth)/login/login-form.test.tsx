import { describe, expect, it } from "vitest";

import { safeNext } from "./login-form";

describe("safeNext", () => {
  it("n'accepte qu'un chemin interne", () => {
    expect(safeNext("/sales?page=2")).toBe("/sales?page=2");
    expect(safeNext(null)).toBe("/dashboard");
    expect(safeNext("https://evil.example")).toBe("/dashboard");
    expect(safeNext("//evil.example")).toBe("/dashboard");
    expect(safeNext("/login")).toBe("/dashboard");
  });
});
