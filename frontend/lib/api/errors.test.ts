import { describe, expect, it } from "vitest";

import { errorMessage, toApiError } from "./errors";

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
    expect(error.message).toMatch(/erreur inattendue/);
  });
});
