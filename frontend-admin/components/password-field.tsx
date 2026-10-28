"use client";

import { useEffect, useId, useState, type InputHTMLAttributes } from "react";

import { FIELD, LABEL } from "@/components/ui";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "autoComplete" | "id"> & {
  label: string;
  autoComplete: "current-password" | "new-password";
  /** Change à chaque envoi du formulaire : le champ se remasque. */
  submitted?: number;
};

/**
 * Champ de mot de passe avec « Afficher / Cacher » (prompt 28, C2, ADR 0098), copié de
 * `frontend/components/password-field.tsx` : les deux applications se déploient
 * séparément, aucune n'importe l'autre. Même comportement : valeur conservée à la
 * bascule, remasqué à l'envoi et quand l'onglet est caché.
 */
export function PasswordField({ label, autoComplete, submitted, ...input }: Props) {
  const id = useId();
  const [shown, setShown] = useState(false);
  const [lastSubmit, setLastSubmit] = useState(submitted);
  if (submitted !== lastSubmit) {
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

  return (
    <div className="space-y-1">
      <label htmlFor={id} className={LABEL}>
        {label}
      </label>
      <div className="relative">
        <input
          {...input}
          id={id}
          type={shown ? "text" : "password"}
          autoComplete={autoComplete}
          autoCapitalize="none"
          spellCheck={false}
          className={`${FIELD} pr-24`}
        />
        <button
          type="button"
          onClick={() => setShown((on) => !on)}
          aria-label={shown ? "Cacher le mot de passe" : "Afficher le mot de passe"}
          aria-pressed={shown}
          className="absolute top-1/2 right-1 inline-flex min-h-11 min-w-11 -translate-y-1/2 items-center justify-center rounded-lg px-3 font-semibold hover:bg-voile"
        >
          {shown ? "Cacher" : "Afficher"}
        </button>
      </div>
    </div>
  );
}
