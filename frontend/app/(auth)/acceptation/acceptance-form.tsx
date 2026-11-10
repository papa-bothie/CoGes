"use client";

import { useState } from "react";

import { SecondaryAction } from "@/components/kit/secondary-action";
import { LegalConsent } from "@/components/legal/legal-consent";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { logout } from "@/lib/auth/session";
import { labels } from "@/lib/labels";

const t = labels.legal.acceptance;

/**
 * La case, puis « Accepter et continuer », inactif tant qu'elle n'est pas cochée. Le serveur
 * enregistre **sa** version courante (`POST /auth/legal-acceptance`, corps vide).
 */
export function AcceptanceForm({ onDone }: { onDone?: () => void }) {
  const [checked, setChecked] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!checked) return;
    setSending(true);
    setError(null);
    try {
      await unwrap(api.POST("/api/v1/auth/legal-acceptance", { body: {} }));
      // Rechargement complet : l'identité en cache disait encore « à accepter ».
      if (onDone) onDone();
      else window.location.replace("/dashboard");
    } catch (failure) {
      setError(errorMessage(failure));
      setSending(false);
    }
  };

  return (
    <form
      noValidate
      className="space-y-5"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      {error && (
        <p
          role="alert"
          className="rounded-champ bg-depenses-teinte px-4 py-3.5 font-bold text-depenses-encre"
        >
          {error}
        </p>
      )}
      <LegalConsent checked={checked} onChange={setChecked} disabled={sending} />
      <button
        type="submit"
        disabled={!checked || sending}
        aria-describedby={checked ? undefined : "acceptation-aide"}
        className="flex min-h-16 w-full items-center justify-center rounded-bouton bg-primary text-xl font-extrabold text-primary-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60"
      >
        {t.submit}
      </button>
      {!checked && (
        <p id="acceptation-aide" className="text-mini text-encre-2">
          {t.hint}
        </p>
      )}
      <SecondaryAction onClick={() => void logout().then(() => window.location.replace("/login"))}>
        {t.logout}
      </SecondaryAction>
    </form>
  );
}
