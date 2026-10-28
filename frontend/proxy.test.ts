import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { proxy } from "./proxy";

const visit = (path: string) => proxy(new NextRequest(new URL(path, "https://coges.app")));

describe("proxy : application installable (ADR 0102)", () => {
  it.each(["/manifest.webmanifest", "/sw.js", "/hors-ligne"])(
    "%s répond sans connexion ni redirection",
    (path) => {
      const response = visit(path);
      expect(response.headers.get("location")).toBeNull();
      expect(response.status).toBe(200);
    },
  );

  it("une page de l'application, elle, renvoie toujours vers la connexion", () => {
    const response = visit("/dashboard");
    expect(response.headers.get("location")).toContain("/login");
  });
});
