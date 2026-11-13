"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { fieldClasses } from "@/components/kit/rubrique";
import { LegalConsent } from "@/components/legal/legal-consent";
import { ButtonLink } from "@/components/vitrine/links";
import { PasswordField } from "@/components/password-field";
import { errorMessage, isApiError } from "@/lib/api/errors";
import { labels } from "@/lib/labels";
import {
  contactSignupTeam,
  createSignupRequest,
  maskEmail,
  resendSignupLink,
} from "@/lib/signup/api";
import { cn } from "@/lib/utils";

const t = labels.signup;
const FIELD = cn(fieldClasses("ventes"), "min-h-[60px] px-[18px] text-[19px]");
export const MIN_PASSWORD = 12;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Step = { kind: "form" } | { kind: "email"; email: string } | { kind: "team" };

type Values = {
  shop_name: string;
  full_name: string;
  phone: string;
  email: string;
  password: string;
  confirm: string;
};
type Errors = Partial<Record<keyof Values, string>>;

/** Chiffres d'un numéro tapé, sans l'indicatif : « +221 77 000 00 00 » → « 770000000 ». */
export function phoneDigits(raw: string): string {
  let digits = raw.replace(/\D/g, "");
  if (digits.startsWith("00")) digits = digits.slice(2);
  if (digits.startsWith("221") && digits.length === 12) digits = digits.slice(3);
  return digits;
}

/** Le numéro envoyé : tel quel s'il porte son indicatif, sinon précédé de +221. Le serveur
 *  le lit avec la même fonction qu'à la connexion (`app/core/phone.py`). */
export function withCountryCode(raw: string): string {
  const typed = raw.trim();
  return /^(\+|00)/.test(typed) ? typed : `+221 ${typed}`;
}

/** Contrôles de surface ; le serveur revalide tout (`SignupRequestCreate`). */
export function validate(values: Values): Errors {
  const errors: Errors = {};
  if (values.shop_name.trim().length < 2) errors.shop_name = t.required;
  if (values.full_name.trim().length < 2) errors.full_name = t.required;
  const digits = phoneDigits(values.phone);
  if (!digits) errors.phone = t.required;
  else if (digits.length < 6 || digits.length > 15) errors.phone = t.phoneInvalid;
  if (values.email.trim() && !EMAIL.test(values.email.trim())) errors.email = t.emailInvalid;
  if (values.password.length < MIN_PASSWORD) errors.password = t.tooShort;
  else if (values.password !== values.confirm) errors.confirm = t.mismatch;
  return errors;
}

/** Le titre de chaque étape reçoit le focus : un lecteur d'écran sait où il est. */
function useStepTitle(step: Step["kind"]) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, [step]);
  return ref;
}

export function SignupFlow({
  instantWithEmail,
  whatsapp,
  supportHours,
  resendSeconds,
}: {
  instantWithEmail: boolean;
  whatsapp: string;
  supportHours: string;
  resendSeconds: number;
}) {
  const [step, setStep] = useState<Step>({ kind: "form" });
  const title = useStepTitle(step.kind);

  if (step.kind === "email") {
    return (
      <CheckEmail
        titleRef={title}
        email={step.email}
        resendSeconds={resendSeconds}
        onTeam={() => setStep({ kind: "team" })}
      />
    );
  }
  if (step.kind === "team") {
    return <Received titleRef={title} whatsapp={whatsapp} supportHours={supportHours} />;
  }
  return (
    <SignupForm
      titleRef={title}
      instantWithEmail={instantWithEmail}
      onDone={(path, email) =>
        setStep(path === "email" && email ? { kind: "email", email } : { kind: "team" })
      }
    />
  );
}

function Title({
  titleRef,
  children,
}: {
  titleRef: React.RefObject<HTMLHeadingElement | null>;
  children: ReactNode;
}) {
  return (
    <h1
      ref={titleRef}
      tabIndex={-1}
      className="text-[32px] leading-tight font-extrabold outline-none"
    >
      {children}
    </h1>
  );
}

function SignupForm({
  titleRef,
  instantWithEmail,
  onDone,
}: {
  titleRef: React.RefObject<HTMLHeadingElement | null>;
  instantWithEmail: boolean;
  onDone: (path: "email" | "team", email: string | null) => void;
}) {
  const [values, setValues] = useState<Values>({
    shop_name: "",
    full_name: "",
    phone: "",
    email: "",
    password: "",
    confirm: "",
  });
  const [errors, setErrors] = useState<Errors>({});
  const [consent, setConsent] = useState(false);
  const [website, setWebsite] = useState("");
  const [sending, setSending] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(0);

  const set = (key: keyof Values) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setValues((current) => ({ ...current, [key]: event.target.value }));

  const submit = async () => {
    setSubmitted((count) => count + 1);
    const found = validate(values);
    setErrors(found);
    if (Object.keys(found).length > 0 || !consent) return;
    setSending(true);
    setFormError(null);
    const email = values.email.trim().toLowerCase() || null;
    try {
      const accepted = await createSignupRequest({
        shop_name: values.shop_name.trim(),
        full_name: values.full_name.trim(),
        phone: withCountryCode(values.phone),
        email,
        password: values.password,
        accept_legal: true,
        website,
      });
      onDone(accepted.path, email);
    } catch (failure) {
      setSending(false);
      setFormError(isApiError(failure) ? failure.message : errorMessage(failure));
    }
  };

  return (
    <div className="space-y-6">
      <Title titleRef={titleRef}>{t.pageTitle}</Title>
      <p className="text-lg text-encre-2">{t.intro}</p>
      <form
        noValidate
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        {formError && (
          <p
            role="alert"
            className="rounded-champ bg-depenses-teinte px-4 py-3.5 font-bold text-depenses-encre"
          >
            {formError}
          </p>
        )}
        <TextField
          label={t.shopName}
          hint={t.shopNameHint}
          value={values.shop_name}
          onChange={set("shop_name")}
          error={errors.shop_name}
          autoComplete="organization"
          maxLength={80}
        />
        <TextField
          label={t.fullName}
          value={values.full_name}
          onChange={set("full_name")}
          error={errors.full_name}
          autoComplete="name"
          maxLength={120}
        />
        <TextField
          label={t.phone}
          hint={t.phoneHint}
          prefix={t.phonePrefix}
          value={values.phone}
          onChange={set("phone")}
          error={errors.phone}
          type="tel"
          inputMode="tel"
          autoComplete="tel-national"
          placeholder="77 000 00 00"
          maxLength={30}
        />
        <TextField
          label={`${t.email} (${t.emailOptional})`}
          hint={instantWithEmail ? t.emailHintInstant : t.emailHintTeam}
          value={values.email}
          onChange={set("email")}
          error={errors.email}
          type="email"
          inputMode="email"
          autoComplete="email"
          autoCapitalize="none"
          spellCheck={false}
          maxLength={254}
        />
        <PasswordField
          label={t.password}
          autoComplete="new-password"
          hint={t.passwordHint}
          value={values.password}
          onChange={set("password")}
          error={errors.password}
          submitted={submitted}
          inputClassName={FIELD}
        />
        <PasswordField
          label={t.confirm}
          autoComplete="new-password"
          value={values.confirm}
          onChange={set("confirm")}
          error={errors.confirm}
          submitted={submitted}
          inputClassName={FIELD}
        />
        {/* Champ piège : invisible et hors du parcours clavier ; un robot le remplit. */}
        <div aria-hidden className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
          <label>
            Site web
            <input
              tabIndex={-1}
              autoComplete="off"
              value={website}
              onChange={(event) => setWebsite(event.target.value)}
            />
          </label>
        </div>
        <LegalConsent checked={consent} onChange={setConsent} disabled={sending} />
        <button
          type="submit"
          disabled={!consent || sending}
          aria-describedby={consent ? undefined : "inscription-aide"}
          className="flex min-h-16 w-full items-center justify-center rounded-bouton bg-primary text-xl font-extrabold text-primary-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60"
        >
          {t.submit}
        </button>
        {!consent && (
          <p id="inscription-aide" className="text-mini text-encre-2">
            {t.consentHint}
          </p>
        )}
      </form>
      <div className="flex flex-wrap items-center gap-3 border-t border-border pt-5">
        <p className="text-lg text-encre-2">{t.alreadyAccount}</p>
        <ButtonLink href="/login" variant="borde">
          {t.login}
        </ButtonLink>
      </div>
    </div>
  );
}

function TextField({
  label,
  hint,
  error,
  prefix,
  ...input
}: React.InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  hint?: string;
  error?: string;
  prefix?: string;
}) {
  const id = useId();
  const hintId = hint ? `${id}-aide` : undefined;
  const errorId = error ? `${id}-erreur` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  const field = (
    <input
      id={id}
      aria-invalid={Boolean(error)}
      aria-describedby={describedBy}
      className={cn(FIELD, prefix && "rounded-l-none")}
      {...input}
    />
  );
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="block text-libelle">
        {label}
      </label>
      {hint && (
        <p id={hintId} className="text-mini text-encre-2">
          {hint}
        </p>
      )}
      {prefix ? (
        <div className="flex">
          <span className="inline-flex items-center rounded-l-champ border-2 border-r-0 border-input bg-voile px-4 text-[19px] font-bold text-encre-2">
            {prefix}
          </span>
          {field}
        </div>
      ) : (
        field
      )}
      {error && (
        <p id={errorId} role="alert" className="font-bold text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

function CheckEmail({
  titleRef,
  email,
  resendSeconds,
  onTeam,
}: {
  titleRef: React.RefObject<HTMLHeadingElement | null>;
  email: string;
  resendSeconds: number;
  onTeam: () => void;
}) {
  const [wait, setWait] = useState(resendSeconds);
  const [status, setStatus] = useState<string | null>(null);
  useEffect(() => {
    if (wait <= 0) return;
    const timer = window.setTimeout(() => setWait((left) => left - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [wait]);

  const resend = async () => {
    try {
      await resendSignupLink(email);
      setStatus(t.resent);
    } catch (failure) {
      setStatus(errorMessage(failure));
    }
    setWait(resendSeconds);
  };
  const team = async () => {
    try {
      await contactSignupTeam(email);
    } finally {
      onTeam();
    }
  };

  return (
    <div className="space-y-6">
      <Title titleRef={titleRef}>{t.checkTitle}</Title>
      <p className="text-lg">{t.checkIntro(maskEmail(email))}</p>
      <p className="text-encre-2">{t.checkHint}</p>
      {status && (
        <p role="status" className="rounded-champ bg-voile px-4 py-3 font-semibold">
          {status}
        </p>
      )}
      <button
        type="button"
        disabled={wait > 0}
        onClick={() => void resend()}
        className="flex min-h-bouton w-full items-center justify-center rounded-bouton border-2 border-input bg-card text-libelle font-bold outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-60"
      >
        {wait > 0 ? t.resendIn(wait) : t.resend}
      </button>
      <button
        type="button"
        onClick={() => void team()}
        className="block min-h-cible text-left font-bold text-success-ink underline underline-offset-4 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {t.noEmail}
      </button>
    </div>
  );
}

function Received({
  titleRef,
  whatsapp,
  supportHours,
}: {
  titleRef: React.RefObject<HTMLHeadingElement | null>;
  whatsapp: string;
  supportHours: string;
}) {
  const display = `+${whatsapp.slice(0, 3)} ${whatsapp.slice(3).replace(/(\d{2})(?=\d)/g, "$1 ")}`;
  return (
    <div className="space-y-6">
      <Title titleRef={titleRef}>{t.receivedTitle}</Title>
      <p className="text-lg">{t.receivedIntro}</p>
      <div className="rounded-carte border border-border bg-card p-5">
        <p className="text-mini font-bold tracking-wide text-encre-2 uppercase">{t.hours}</p>
        <p className="text-lg">{supportHours}</p>
        <a
          href={`https://wa.me/${whatsapp}`}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 inline-flex min-h-cible items-center font-bold text-success-ink underline underline-offset-4"
        >
          {t.whatsapp} ({display})
        </a>
      </div>
      <section aria-labelledby="ensuite" className="space-y-3">
        <h2 id="ensuite" className="text-[22px] font-extrabold">
          {t.nextTitle}
        </h2>
        <ol className="list-decimal space-y-2 pl-6 text-lg marker:font-bold">
          {t.nextSteps.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ol>
      </section>
      <Link
        href="/"
        className="inline-flex min-h-cible items-center font-bold underline underline-offset-4"
      >
        {t.backHome}
      </Link>
    </div>
  );
}
