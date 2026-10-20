/** Erreur de l'API au format `{ error: { code, message, details } }`. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

type Envelope = { error?: { code?: unknown; message?: unknown; details?: unknown } };

export function toApiError(status: number, body: unknown): ApiError {
  const error = (body as Envelope | null)?.error;
  if (error && typeof error.code === "string" && typeof error.message === "string") {
    const details =
      error.details && typeof error.details === "object"
        ? (error.details as Record<string, unknown>)
        : {};
    return new ApiError(status, error.code, error.message, details);
  }
  return new ApiError(
    status,
    status >= 500 ? "server_error" : "unknown_error",
    "Le serveur n'a pas pu répondre. Réessayez dans un instant.",
  );
}

export function networkError(): ApiError {
  return new ApiError(0, "network_error", "Connexion impossible au serveur. Vérifiez le réseau.");
}

/** Message à afficher : celui du serveur (en français), sinon une phrase générique. */
export function errorMessage(error: unknown): string {
  return isApiError(error) ? error.message : "Une erreur inattendue est survenue.";
}
