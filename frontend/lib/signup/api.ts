import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/types/api";

/** Appels publics de l'inscription (ADR 0118) : sans jeton, jamais de rafraîchissement. */
export type SignupForm = components["schemas"]["SignupRequestCreate"];
export type SignupAccepted = components["schemas"]["SignupRequestAccepted"];
export type SignupVerified = components["schemas"]["SignupVerified"];

export function createSignupRequest(body: SignupForm): Promise<SignupAccepted> {
  return unwrap(api.POST("/api/v1/auth/signup-requests", { body }));
}

export function verifySignupLink(token: string): Promise<SignupVerified> {
  return unwrap(api.POST("/api/v1/auth/signup-requests/verify", { body: { token } }));
}

export function resendSignupLink(email: string): Promise<unknown> {
  return unwrap(api.POST("/api/v1/auth/signup-requests/resend", { body: { email } }));
}

export function contactSignupTeam(email: string): Promise<unknown> {
  return unwrap(api.POST("/api/v1/auth/signup-requests/contact-team", { body: { email } }));
}

/** « awa.ndiaye@example.com » → « a••••••••@example.com » : l'adresse n'est pas répétée. */
export function maskEmail(email: string): string {
  const [name = "", domain = ""] = email.split("@");
  if (!domain) return email;
  return `${name.charAt(0)}${"•".repeat(Math.max(name.length - 1, 3))}@${domain}`;
}
