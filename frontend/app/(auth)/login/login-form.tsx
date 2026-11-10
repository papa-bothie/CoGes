"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useSearchParams } from "next/navigation";
import { useEffect, useId, useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { fieldClasses } from "@/components/kit/rubrique";
import { PasswordField } from "@/components/password-field";
import { isApiError, errorMessage } from "@/lib/api/errors";
import { safeNext } from "@/lib/auth/safe-next";
import { COMPANY_SUSPENDED, login } from "@/lib/auth/session";
import { resendSignupLink } from "@/lib/signup/api";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

const t = labels.login;

/** Mêmes bornes que `LoginRequest` côté API ; le serveur revalide de toute façon. */
const loginSchema = z.object({
  company_slug: z
    .string()
    .trim()
    .toLowerCase()
    .regex(/^[a-z0-9-]{3,40}$/, labels.validation.slug),
  identifier: z.string().trim().min(1, labels.validation.required).max(254),
  password: z.string().min(1, labels.validation.required).max(128),
});

type LoginInput = z.input<typeof loginSchema>;
type LoginValues = z.output<typeof loginSchema>;

const LAST_SLUG_KEY = "coges:last-company-slug";
const FIELD = cn(fieldClasses("ventes"), "min-h-[60px] px-[18px] text-[19px]");

function rememberedSlug(): string {
  try {
    return localStorage.getItem(LAST_SLUG_KEY) ?? "";
  } catch {
    return "";
  }
}

/** Le message d'un refus, en phrase : jamais « Identifiants invalides. ». */
function failure(error: unknown): string {
  // Provisoire expiré (ADR 0078) : ne s'apprend qu'avec le bon mot de passe.
  if (isApiError(error) && error.code === "temporary_password_expired") return t.temporaryExpired;
  // Entreprise suspendue (ADR 0089) : le bon mot de passe, mais l'accès est coupé.
  if (isApiError(error) && error.code === COMPANY_SUSPENDED) return t.suspended;
  // Demande d'inscription pas encore activée (ADR 0118) : dit après le bon mot de passe.
  if (isApiError(error) && error.code === "signup_email_pending") return t.signupEmailPending;
  if (isApiError(error) && error.code === "signup_team_pending") return t.signupTeamPending;
  if (isApiError(error) && error.status === 401) return t.invalid;
  // Freinage par compte : le serveur dit combien de minutes attendre.
  if (isApiError(error) && error.status === 429 && error.details.scope === "account") {
    return error.message;
  }
  if (isApiError(error) && error.status === 429) return t.tooMany;
  return errorMessage(error);
}

export function LoginForm() {
  const params = useSearchParams();
  const reason = params.get("reason");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(0);
  // Lien e-mail à renvoyer, quand la connexion a révélé une demande en attente (ADR 0118).
  const [resendTo, setResendTo] = useState<string | null>(null);
  const [resent, setResent] = useState(false);

  const {
    register,
    handleSubmit,
    setValue,
    setFocus,
    formState: { errors, isSubmitting },
  } = useForm<LoginInput, unknown, LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { company_slug: "", identifier: "", password: "" },
  });

  useEffect(() => {
    // Code de boutique prérempli depuis « Votre boutique est prête » ou l'e-mail de
    // bienvenue (`?boutique=`), avant celui de la dernière connexion (ADR 0118).
    const given = params.get("boutique")?.trim().toLowerCase() ?? "";
    const slug = /^[a-z0-9-]{3,40}$/.test(given) ? given : rememberedSlug();
    if (slug) {
      setValue("company_slug", slug);
      setFocus("identifier");
    } else {
      setFocus("company_slug");
    }
  }, [setValue, setFocus, params]);

  const onSubmit = async (values: LoginValues) => {
    setFormError(null);
    setResendTo(null);
    setResent(false);
    try {
      await login(values);
    } catch (error) {
      setFormError(failure(error));
      if (isApiError(error) && error.code === "signup_email_pending") {
        setResendTo(values.identifier.includes("@") ? values.identifier : null);
      }
      return;
    }
    try {
      localStorage.setItem(LAST_SLUG_KEY, values.company_slug);
    } catch {
      // Stockage indisponible (navigation privée) : simple confort perdu.
    }
    // Rechargement complet vers l'application : `proxy.ts` voit l'indicateur de session.
    window.location.assign(safeNext(params.get("next"), window.location.origin));
  };

  const notices: Record<string, string> = {
    expired: t.sessionExpired,
    logout: t.loggedOut,
    suspended: t.suspended,
  };
  const notice = reason ? (notices[reason] ?? null) : null;

  return (
    <form
      onSubmit={(event) => {
        // Le mot de passe se remasque à chaque envoi (ADR 0098).
        setSubmitted((count) => count + 1);
        void handleSubmit(onSubmit)(event);
      }}
      noValidate
      className="space-y-5"
    >
      {notice && !formError && (
        <p role="status" className="rounded-champ bg-voile px-4 py-3 font-semibold">
          {notice}
        </p>
      )}
      {formError && (
        <p
          role="alert"
          className="rounded-champ bg-depenses-teinte px-4 py-3.5 font-bold text-depenses-encre"
        >
          {formError}
          {resendTo && !resent && (
            <button
              type="button"
              onClick={() => void resendSignupLink(resendTo).then(() => setResent(true))}
              className="mt-2 block min-h-cible font-bold underline underline-offset-4 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {t.signupResend}
            </button>
          )}
        </p>
      )}
      {resent && (
        <p role="status" className="rounded-champ bg-voile px-4 py-3 font-semibold">
          {t.signupResent}
        </p>
      )}

      <Field label={t.companySlug} error={errors.company_slug?.message}>
        {(id, describedBy) => (
          <input
            id={id}
            autoComplete="organization"
            autoCapitalize="none"
            spellCheck={false}
            aria-invalid={Boolean(errors.company_slug)}
            aria-describedby={describedBy}
            className={FIELD}
            {...register("company_slug")}
          />
        )}
      </Field>

      <Field label={t.identifier} error={errors.identifier?.message}>
        {(id, describedBy) => (
          <input
            id={id}
            inputMode="email"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            aria-invalid={Boolean(errors.identifier)}
            aria-describedby={describedBy}
            className={FIELD}
            {...register("identifier")}
          />
        )}
      </Field>

      <PasswordField
        label={t.password}
        autoComplete="current-password"
        error={errors.password?.message}
        submitted={submitted}
        inputClassName={FIELD}
        {...register("password")}
      />

      <button
        type="submit"
        disabled={isSubmitting}
        className="flex min-h-16 w-full items-center justify-center rounded-bouton bg-primary text-xl font-extrabold text-primary-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60"
      >
        {isSubmitting ? t.submitting : t.submit}
      </button>
      <p className="text-[17px] text-encre-2">{t.forgot}</p>
    </form>
  );
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: (id: string, describedBy: string | undefined) => ReactNode;
}) {
  const id = useId();
  const errorId = `${id}-erreur`;
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="block text-libelle">
        {label}
      </label>
      {children(id, error ? errorId : undefined)}
      {error && (
        <p id={errorId} className="font-semibold text-depenses-encre">
          {error}
        </p>
      )}
    </div>
  );
}
