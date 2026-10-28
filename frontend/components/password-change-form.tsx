"use client";

import { useState } from "react";

import { PasswordField } from "@/components/password-field";
import { fieldClasses } from "@/components/kit/rubrique";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

const t = labels.login.firstPassword;
/** Même borne que `PasswordUpdate` côté API ; le serveur revérifie. */
export const MIN_PASSWORD_LENGTH = 12;
const FIELD = cn(fieldClasses("ventes"), "min-h-[60px] px-[18px] text-[19px]");

/**
 * Mot de passe actuel, puis le nouveau deux fois (`POST /auth/password`). Sert à la
 * première connexion et à « Changer mon mot de passe » (prompt 28, C2, ADR 0098) : la
 * règle de longueur est affichée avant toute erreur, la concordance vérifiée avant
 * l'envoi, et le serveur revérifie tout.
 */
export function PasswordChangeForm({
  currentLabel,
  submitLabel,
  onDone,
  children,
}: {
  currentLabel: string;
  submitLabel: string;
  onDone: () => void;
  children?: React.ReactNode;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [submitted, setSubmitted] = useState(0);

  const submit = async () => {
    setSubmitted((count) => count + 1);
    if (next.length < MIN_PASSWORD_LENGTH) return setError(t.tooShort);
    if (next !== again) return setError(t.mismatch);
    setError(null);
    setSending(true);
    try {
      await unwrap(
        api.POST("/api/v1/auth/password", {
          body: { current_password: current, new_password: next },
        }),
      );
      onDone();
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
      <PasswordField
        label={currentLabel}
        autoComplete="current-password"
        value={current}
        onChange={(event) => setCurrent(event.target.value)}
        submitted={submitted}
        inputClassName={FIELD}
      />
      <PasswordField
        label={t.next}
        autoComplete="new-password"
        value={next}
        onChange={(event) => setNext(event.target.value)}
        hint={t.nextHint}
        submitted={submitted}
        inputClassName={FIELD}
      />
      <PasswordField
        label={t.confirm}
        autoComplete="new-password"
        value={again}
        onChange={(event) => setAgain(event.target.value)}
        submitted={submitted}
        inputClassName={FIELD}
      />
      <button
        type="submit"
        disabled={sending || !current || !next || !again}
        className="flex min-h-16 w-full items-center justify-center rounded-bouton bg-primary text-xl font-extrabold text-primary-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60"
      >
        {submitLabel}
      </button>
      {children}
    </form>
  );
}
