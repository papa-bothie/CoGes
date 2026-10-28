"use client";

import { forwardRef, useEffect, useId, useState, type InputHTMLAttributes } from "react";

import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

const t = labels.login;

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "autoComplete" | "id"> & {
  label: string;
  /** `current-password` à la connexion, `new-password` pour en choisir un. */
  autoComplete: "current-password" | "new-password";
  hint?: string;
  error?: string;
  /** Passe à `true` à chaque envoi du formulaire : le champ se remasque. */
  submitted?: number;
  inputClassName?: string;
};

/**
 * Champ de mot de passe avec « Afficher / Cacher » (prompt 28, C2, ADR 0098). La valeur
 * reste la même quand on bascule ; le champ se remasque à l'envoi (`submitted` change) et
 * quand l'onglet est caché. La valeur ne quitte jamais le champ : ni adresse, ni journal.
 */
export const PasswordField = forwardRef<HTMLInputElement, Props>(function PasswordField(
  { label, autoComplete, hint, error, submitted, inputClassName, className, ...input },
  ref,
) {
  const id = useId();
  const [shown, setShown] = useState(false);
  const [lastSubmit, setLastSubmit] = useState(submitted);
  if (submitted !== lastSubmit) {
    // Remasqué à chaque envoi, sans effet : l'état suit la prop pendant le rendu.
    setLastSubmit(submitted);
    if (shown) setShown(false);
  }

  useEffect(() => {
    const hide = () => {
      if (document.visibilityState === "hidden") setShown(false);
    };
    document.addEventListener("visibilitychange", hide);
    return () => document.removeEventListener("visibilitychange", hide);
  }, []);

  const hintId = hint ? `${id}-aide` : undefined;
  const errorId = error ? `${id}-erreur` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={cn("space-y-2", className)}>
      <label htmlFor={id} className="block text-libelle">
        {label}
      </label>
      <div className="relative">
        <input
          {...input}
          ref={ref}
          id={id}
          type={shown ? "text" : "password"}
          autoComplete={autoComplete}
          autoCapitalize="none"
          spellCheck={false}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={cn(inputClassName, "pr-28")}
        />
        <button
          type="button"
          onClick={() => setShown((on) => !on)}
          aria-label={shown ? t.hidePassword : t.showPassword}
          aria-pressed={shown}
          className="absolute top-1/2 right-1.5 min-h-12 min-w-11 -translate-y-1/2 rounded-touche bg-voile px-3.5 font-bold outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {shown ? t.hide : t.show}
        </button>
      </div>
      {hint && (
        <p id={hintId} className="text-encre-2">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="font-semibold text-depenses-encre">
          {error}
        </p>
      )}
    </div>
  );
});
