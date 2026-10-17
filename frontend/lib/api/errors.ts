import { labels } from "@/lib/labels";

/**
 * Enveloppe d'erreur de l'API : `{ "error": { "code", "message", "details" } }`.
 * `code` est stable (anglais, snake_case) ; `message` est déjà en français.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  /** Identifiant de la requête (en-tête `X-Request-Id`), lu comme référence d'incident. */
  readonly requestId: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  /** Erreurs de champ d'un 422 : `{ "email": "…" }`. */
  fieldErrors(): Record<string, string> {
    const fields = this.details.fields;
    if (!Array.isArray(fields)) return {};
    const result: Record<string, string> = {};
    for (const entry of fields) {
      if (entry && typeof entry === "object" && typeof entry.field === "string") {
        result[entry.field] ??= labels.validation.invalidValue;
      }
    }
    return result;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Traduit un corps de réponse en `ApiError`, même s'il n'a pas le format attendu (une page
 * de maintenance de Caddy en 502, par exemple). La référence vient du corps, sinon de
 * l'en-tête `X-Request-Id`.
 */
export function toApiError(
  status: number,
  body: unknown,
  headerRequestId: string | null = null,
): ApiError {
  if (isRecord(body) && isRecord(body.error)) {
    const { code, message, details, request_id } = body.error;
    return new ApiError(
      status,
      typeof code === "string" ? code : "unknown_error",
      typeof message === "string" ? message : labels.errors.generic,
      isRecord(details) ? details : {},
      typeof request_id === "string" ? request_id : headerRequestId,
    );
  }
  return new ApiError(
    status,
    status >= 500 ? "server_error" : "unknown_error",
    status >= 500 ? labels.incident.body : labels.errors.generic,
    {},
    headerRequestId,
  );
}

/** Coupure réseau, ou API arrêtée derrière Caddy : un nouvel essai a des chances de passer. */
export function isTransient(error: unknown): boolean {
  return isApiError(error) && (error.status === 0 || [502, 503, 504].includes(error.status));
}

export function networkError(): ApiError {
  return new ApiError(0, "network_error", labels.errors.network);
}

/** Message à montrer à l'utilisateur pour n'importe quelle erreur. */
export function errorMessage(error: unknown): string {
  if (isApiError(error)) return error.message;
  return labels.errors.generic;
}
