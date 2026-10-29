import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/errors";

import { MESSAGES, failure } from "./login-form";

describe("messages de connexion de l'administration", () => {
  it("un refus ne dit pas lequel de l'e-mail ou du mot de passe est faux", () => {
    expect(failure(new ApiError(401, "authentication_required", "Identifiants invalides."))).toBe(
      MESSAGES.invalid,
    );
  });

  it("le freinage par compte rend la phrase du serveur", () => {
    const error = new ApiError(429, "rate_limited", "Trop d'essais. Réessayez dans 2 minutes.", {
      scope: "account",
    });
    expect(failure(error)).toBe("Trop d'essais. Réessayez dans 2 minutes.");
  });

  it("le plafond par adresse a sa phrase générique", () => {
    expect(failure(new ApiError(429, "rate_limited", "…", { scope: "login" }))).toBe(
      MESSAGES.tooMany,
    );
  });

  it("sans passage par Cloudflare Access, la phrase du serveur dit quoi faire (ADR 0104)", () => {
    const message =
      "Ouvrez l'administration depuis son adresse habituelle : l'accès passe par la " +
      "vérification Cloudflare.";
    expect(failure(new ApiError(403, "access_required", message))).toBe(message);
  });
});
