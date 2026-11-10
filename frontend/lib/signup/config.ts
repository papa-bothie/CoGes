import type { components } from "@/types/api";

export type SignupConfig = components["schemas"]["SignupConfig"];

/** L'état revu au plus toutes les 5 minutes (ADR 0118) : ouvrir ou fermer l'inscription
 *  se voit sur la vitrine et la connexion sans reconstruire le front. */
export const SIGNUP_REVALIDATE_SECONDS = 300;

const CLOSED: SignupConfig = {
  enabled: false,
  instant_with_email: false,
  support_whatsapp: "",
  resend_interval_seconds: 60,
};

function apiOrigin(): string {
  const value = process.env.COGES_API_URL;
  return value ? value.replace(/\/+$/, "") : "http://localhost:8000";
}

/**
 * Lu **par le serveur Next**, jamais par le navigateur : la vitrine reste sans appel à
 * l'API (ADR 0115). API injoignable (build de l'image, panne) : inscription « fermée »,
 * le bouton reste caché plutôt que de mener à une page qui échouerait.
 */
export async function signupConfig(): Promise<SignupConfig> {
  try {
    const response = await fetch(`${apiOrigin()}/api/v1/auth/signup-config`, {
      next: { revalidate: SIGNUP_REVALIDATE_SECONDS },
      signal: AbortSignal.timeout(2000),
    });
    if (!response.ok) return CLOSED;
    return { ...CLOSED, ...((await response.json()) as Partial<SignupConfig>) };
  } catch {
    return CLOSED;
  }
}
