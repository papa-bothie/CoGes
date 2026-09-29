import { labels } from "@/lib/labels";

/**
 * Enveloppe d'erreur de l'API : `{ "error": { "code", "message", "details" } }`.
 * `code` est stable (anglais, snake_case) ; `message` est déjà en français.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
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

/** Traduit un corps de réponse en `ApiError`, même s'il n'a pas le format attendu. */
export function toApiError(status: number, body: unknown): ApiError {
  if (isRecord(body) && isRecord(body.error)) {
    const { code, message, details } = body.error;
    return new ApiError(
      status,
      typeof code === "string" ? code : "unknown_error",
      typeof message === "string" ? message : labels.errors.generic,
      isRecord(details) ? details : {},
    );
  }
  return new ApiError(
    status,
    status >= 500 ? "server_error" : "unknown_error",
    labels.errors.generic,
  );
}

export function networkError(): ApiError {
  return new ApiError(0, "network_error", labels.errors.network);
}

/** Message à montrer à l'utilisateur pour n'importe quelle erreur. */
export function errorMessage(error: unknown): string {
  if (isApiError(error)) return error.message;
  return labels.errors.generic;
}
