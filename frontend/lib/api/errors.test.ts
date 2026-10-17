import { describe, expect, it } from "vitest";

import { errorMessage, isTransient, networkError, toApiError } from "./errors";

describe("toApiError", () => {
  it("lit l'enveloppe d'erreur de l'API", () => {
    const error = toApiError(409, {
      error: {
        code: "insufficient_stock",
        message: "Stock insuffisant — 3 unités disponibles.",
        details: { available: "3.000" },
      },
    });
    expect(error.status).toBe(409);
    expect(error.code).toBe("insufficient_stock");
    expect(errorMessage(error)).toBe("Stock insuffisant — 3 unités disponibles.");
    expect(error.details).toEqual({ available: "3.000" });
  });

  it("traduit les erreurs de champ d'un 422", () => {
    const error = toApiError(422, {
      error: {
        code: "validation_failed",
        message: "Données invalides.",
        details: { fields: [{ field: "email", message: "value is not a valid email" }] },
      },
    });
    expect(Object.keys(error.fieldErrors())).toEqual(["email"]);
  });

  it("reste lisible sur un corps inattendu", () => {
    const error = toApiError(502, "<html>Bad gateway</html>");
    expect(error.code).toBe("server_error");
    expect(error.message).toMatch(/Un souci de notre côté/);
    expect(toApiError(418, "<html>?</html>").message).toMatch(/erreur inattendue/);
  });
});

describe("erreur serveur et référence d'incident (ADR 0085)", () => {
  it("lit la référence dans le corps d'une 500", () => {
    const error = toApiError(500, {
      error: { code: "server_error", message: "Un souci", details: {}, request_id: "abcd-1234" },
    });
    expect(error.requestId).toBe("abcd-1234");
  });

  it("prend l'en-tête quand le corps n'est pas celui de l'API (page de maintenance)", () => {
    const error = toApiError(502, "<html>…</html>", "ef56-7890");
    expect(error.code).toBe("server_error");
    expect(error.requestId).toBe("ef56-7890");
    expect(error.message).toContain("Vos données sont en sécurité");
  });

  it("reconnaît une coupure qui vaut un nouvel essai", () => {
    expect(isTransient(networkError())).toBe(true);
    expect(isTransient(toApiError(503, null))).toBe(true);
    expect(isTransient(toApiError(500, null))).toBe(false);
    expect(isTransient(toApiError(409, null))).toBe(false);
  });
});
