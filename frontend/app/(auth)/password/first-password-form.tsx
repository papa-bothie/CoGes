"use client";

import { useId, useState } from "react";

import { fieldClasses } from "@/components/kit/rubrique";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { logout } from "@/lib/auth/session";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

const t = labels.login.firstPassword;
const MIN_LENGTH = 12;
const FIELD = cn(fieldClasses("ventes"), "min-h-[60px] px-[18px] text-[19px]");

/**
 * Le mot de passe reçu, puis le nouveau deux fois. Le serveur revérifie tout (longueur,
 * mot de passe actuel, différent de l'ancien) et lève l'obligation (`POST /auth/password`).
 */
export function FirstPasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const submit = async () => {
    if (next.length < MIN_LENGTH) return setError(t.tooShort);
    if (next !== again) return setError(t.mismatch);
    setError(null);
    setSending(true);
    try {
      await unwrap(
        api.POST("/api/v1/auth/password", {
          body: { current_password: current, new_password: next },
        }),
      );
      // Rechargement complet : l'identité en cache disait encore « à changer ».
      window.location.replace("/dashboard");
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
      <PasswordField label={t.current} value={current} onChange={setCurrent} current />
      <PasswordField label={t.next} value={next} onChange={setNext} hint={t.nextHint} />
      <PasswordField label={t.confirm} value={again} onChange={setAgain} />
      <button
        type="submit"
        disabled={sending || !current || !next || !again}
        className="flex min-h-16 w-full items-center justify-center rounded-bouton bg-primary text-xl font-extrabold text-primary-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60"
      >
        {t.submit}
      </button>
      <button
        type="button"
        onClick={() => void logout().then(() => window.location.replace("/login"))}
        className="min-h-12 font-semibold text-encre-2 underline-offset-4 hover:underline"
      >
        {t.logout}
      </button>
    </form>
  );
}

function PasswordField({
  label,
  value,
  onChange,
  hint,
  current = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  current?: boolean;
}) {
  const id = useId();
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="block text-libelle">
        {label}
      </label>
      <input
        id={id}
        type="password"
        autoComplete={current ? "current-password" : "new-password"}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-describedby={hint ? `${id}-aide` : undefined}
        className={FIELD}
      />
      {hint && (
        <p id={`${id}-aide`} className="text-encre-2">
          {hint}
        </p>
      )}
    </div>
  );
}
