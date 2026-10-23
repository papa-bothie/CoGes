"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useId, useState, type FormEvent } from "react";

import { errorMessage, isApiError } from "@/lib/api/errors";
import { login } from "@/lib/auth/session";

export const MESSAGES = {
  invalid: "E-mail ou mot de passe incorrect.",
  tooMany: "Trop d'essais. Attendez avant de réessayer.",
  expired: "Votre session a expiré. Reconnectez-vous.",
  required: "Renseignez l'e-mail et le mot de passe.",
};

export function failure(error: unknown): string {
  if (isApiError(error) && error.status === 401) return MESSAGES.invalid;
  // Freinage par compte : le serveur dit combien de minutes attendre.
  if (isApiError(error) && error.status === 429) {
    return error.details.scope === "account" ? error.message : MESSAGES.tooMany;
  }
  return errorMessage(error);
}

export function LoginForm() {
  const params = useSearchParams();
  const router = useRouter();
  const emailId = useId();
  const passwordId = useId();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim() || !password) {
      setError(MESSAGES.required);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
    } catch (caught) {
      setError(failure(caught));
      setBusy(false);
      return;
    }
    // `proxy.ts` voit désormais l'indicateur de session posé par `login`.
    router.replace("/companies");
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      {params.get("reason") === "expired" && !error && (
        <p role="status" className="rounded bg-attention-teinte px-3 py-2 text-attention">
          {MESSAGES.expired}
        </p>
      )}
      {error && (
        <p role="alert" className="rounded bg-danger-teinte px-3 py-2 font-semibold text-danger">
          {error}
        </p>
      )}
      <div className="space-y-1">
        <label htmlFor={emailId} className="block font-semibold">
          E-mail
        </label>
        <input
          id={emailId}
          type="email"
          autoComplete="username"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="w-full rounded border border-trait bg-surface px-3 py-2"
        />
      </div>
      <div className="space-y-1">
        <label htmlFor={passwordId} className="block font-semibold">
          Mot de passe
        </label>
        <input
          id={passwordId}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="w-full rounded border border-trait bg-surface px-3 py-2"
        />
      </div>
      <button
        type="submit"
        disabled={busy}
        className="w-full rounded bg-accent px-4 py-2.5 font-semibold text-accent-encre disabled:opacity-60"
      >
        {busy ? "Connexion…" : "Se connecter"}
      </button>
    </form>
  );
}
