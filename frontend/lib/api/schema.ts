/**
 * Alias lisibles sur les types **générés** (`types/api.ts`, `pnpm gen:api`).
 * Aucun type d'API n'est écrit à la main : on ne fait ici que les nommer.
 */
import type { components, paths } from "@/types/api";

export type { components, paths };

export type Schemas = components["schemas"];
export type Me = Schemas["MeResponse"];
export type LoginRequest = Schemas["LoginRequest"];
export type TokenResponse = Schemas["TokenResponse"];
