import { createHmac } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, type APIRequestContext, type Page } from "@playwright/test";

/**
 * Double authentification des parcours (ADR 0105). Le compte de l'équipe des parcours est
 * créé avec ce secret (`e2e.sh reset`, `--mfa-secret`, refusé hors local et CI) ; les
 * codes sont calculés ici, comme une application Authenticator (RFC 6238, SHA-1, 30 s,
 * 6 chiffres).
 *
 * Un code ne sert qu'une fois (anti-rejeu) : le dernier pas utilisé par compte est gardé
 * dans un fichier, et chaque connexion prend le pas suivant, dans la tolérance d'un pas
 * du serveur — ou attend le prochain.
 */
export const ADMIN = {
  email: "admin@e2e.example.com",
  password: "admin-coges-e2e-2026",
  secret: "COGESEXADMINQMFAQSECRETQAAAAAAAA",
};
export const API = "http://localhost:8100/api/v1";

const STEP_MS = 30_000;
const LEDGER = path.resolve(__dirname, "../../.e2e-access/totp-steps.json");

function base32(secret: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of secret.replace(/=+$/, "")) {
    bits += alphabet.indexOf(char).toString(2).padStart(5, "0");
  }
  const bytes = bits.match(/.{8}/g) ?? [];
  return Buffer.from(bytes.map((byte) => parseInt(byte, 2)));
}

export function totp(secret: string, step: number): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(step));
  const digest = createHmac("sha1", base32(secret)).update(counter).digest();
  const offset = digest[digest.length - 1]! & 0x0f;
  const value = digest.readUInt32BE(offset) & 0x7fffffff;
  return String(value % 1_000_000).padStart(6, "0");
}

function readLedger(): Record<string, number> {
  try {
    return JSON.parse(readFileSync(LEDGER, "utf-8")) as Record<string, number>;
  } catch {
    return {};
  }
}

/** Un code jamais servi pour ce secret : le pas suivant le dernier utilisé. */
export async function freshCode(secret: string): Promise<string> {
  const ledger = readLedger();
  const now = Math.floor(Date.now() / STEP_MS);
  const step = Math.max(now - 1, (ledger[secret] ?? 0) + 1);
  // Le serveur accepte au plus le pas suivant : au-delà, on attend qu'il arrive.
  const waitMs = (step - 1) * STEP_MS - Date.now();
  if (waitMs > 0) await new Promise((resolve) => setTimeout(resolve, waitMs + 500));
  mkdirSync(path.dirname(LEDGER), { recursive: true });
  writeFileSync(LEDGER, JSON.stringify({ ...ledger, [secret]: step }));
  return totp(secret, step);
}

/** Le code de l'application, sur l'écran qui suit le mot de passe. */
export async function enterCode(page: Page, secret = ADMIN.secret): Promise<void> {
  await page.getByLabel("Code à 6 chiffres").fill(await freshCode(secret));
  await page.getByRole("button", { name: "Valider" }).click();
}

/** Connexion complète de l'équipe des parcours : mot de passe, puis code. */
export async function signInAdmin(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(ADMIN.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await enterCode(page);
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
}

/** Jeton d'accès par l'API seule, pour préparer un parcours. */
export async function apiToken(
  request: APIRequestContext,
  account: { email: string; password: string; secret: string } = ADMIN,
): Promise<string> {
  const step = await request.post(`${API}/platform/auth/login`, {
    data: { email: account.email, password: account.password },
  });
  expect(step.ok()).toBeTruthy();
  const verified = await request.post(`${API}/platform/auth/mfa/verify`, {
    data: {
      challenge_token: (await step.json()).challenge_token,
      code: await freshCode(account.secret),
    },
  });
  expect(verified.ok()).toBeTruthy();
  return (await verified.json()).access_token as string;
}

/** Enrôle un compte par l'API (jeton intermédiaire `enroll`) ; rend son secret. */
export async function enrollByApi(request: APIRequestContext, challenge: string): Promise<string> {
  const proposed = await request.post(`${API}/platform/auth/mfa/enrollment`, {
    data: { challenge_token: challenge },
  });
  expect(proposed.ok()).toBeTruthy();
  const secret = (await proposed.json()).secret as string;
  const activated = await request.post(`${API}/platform/auth/mfa/enrollment/confirm`, {
    data: { challenge_token: challenge, code: await freshCode(secret) },
  });
  expect(activated.ok()).toBeTruthy();
  return secret;
}

/**
 * Enrôlement à l'écran : lit la clé texte affichée, saisit le premier code, garde les
 * codes de secours et entre. Rend le secret et les codes.
 */
export async function enrollOnScreen(page: Page): Promise<{ secret: string; codes: string[] }> {
  await expect(page.getByRole("img", { name: /QR code à scanner/ })).toBeVisible();
  const secret = (await page.getByText(/^[A-Z2-7]{4}( [A-Z2-7]{4}){7}$/).innerText()).replace(
    / /g,
    "",
  );
  await page.getByLabel("Code à 6 chiffres").fill(await freshCode(secret));
  await page.getByRole("button", { name: "Activer la double authentification" }).click();
  const list = page.getByRole("list", { name: "Codes de secours" });
  await expect(list.getByRole("listitem")).toHaveCount(10);
  const codes = await list.getByRole("listitem").allInnerTexts();
  return { secret, codes };
}

/** Après les codes de secours : la case, puis l'entrée dans l'administration. */
export async function keepCodesAndEnter(page: Page): Promise<void> {
  await page.getByLabel("J'ai rangé ces codes en lieu sûr.").check();
  await page.getByRole("button", { name: "Continuer vers l'administration" }).click();
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
}
