"use client";

import { Check, Copy, KeyRound, Printer, Smartphone } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { BUTTON, FIELD, LABEL } from "@/components/ui";
import { isApiError } from "@/lib/api/errors";
import { confirmEnrollment, startEnrollment, verifyMfa, type Enrollment } from "@/lib/auth/session";

/**
 * Double authentification de l'administration (ADR 0105) : la seconde étape de la
 * connexion, l'enrôlement et les codes de secours. Rien ici n'est gardé hors de la
 * mémoire de la page : ni le jeton intermédiaire, ni le secret, ni les codes.
 */

export const MFA_MESSAGES = {
  wrongCode: "Code incorrect. Vérifiez l'heure de votre téléphone et réessayez.",
  wrongRecovery: "Code de secours incorrect ou déjà utilisé.",
  expired: "Cette étape a expiré. Reprenez la connexion depuis le début.",
  tooMany: "Trop d'essais. Attendez avant de réessayer.",
  codeRequired: "Saisissez les 6 chiffres affichés par votre application.",
  recoveryRequired: "Saisissez un de vos codes de secours (8 caractères).",
  offline: "Le service ne répond pas. Réessayez dans un instant.",
};

/** Le message d'un refus ; `expired` : le jeton intermédiaire ne sert plus. */
export function mfaFailure(
  error: unknown,
  recovery = false,
): { message: string; expired: boolean } {
  if (isApiError(error)) {
    if (error.code === "mfa_challenge_invalid")
      return { message: MFA_MESSAGES.expired, expired: true };
    if (error.code === "mfa_code_invalid") {
      return {
        message: recovery ? MFA_MESSAGES.wrongRecovery : MFA_MESSAGES.wrongCode,
        expired: false,
      };
    }
    if (error.status === 429) {
      return {
        message: error.details.scope === "account" ? error.message : MFA_MESSAGES.tooMany,
        expired: false,
      };
    }
    if (error.status > 0) return { message: error.message, expired: false };
  }
  return { message: MFA_MESSAGES.offline, expired: false };
}

/** Six chiffres ; espaces tolérés, le reste retiré à la saisie. */
export function cleanCode(value: string): string {
  return value.replace(/[^\d]/g, "").slice(0, 6);
}

function Alert({ children }: { children: string }) {
  return (
    <p role="alert" className="rounded-lg bg-danger-teinte px-3 py-2 font-semibold text-danger">
      {children}
    </p>
  );
}

export function CodeField({
  value,
  onChange,
  label = "Code à 6 chiffres",
  hint,
}: {
  value: string;
  onChange: (value: string) => void;
  label?: string;
  hint?: string;
}) {
  const id = useId();
  const hintId = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className={LABEL}>
        {label}
      </label>
      {hint && (
        <p id={hintId} className="text-sm text-encre-douce">
          {hint}
        </p>
      )}
      <input
        id={id}
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]*"
        maxLength={7}
        aria-describedby={hint ? hintId : undefined}
        value={value}
        onChange={(event) => onChange(cleanCode(event.target.value))}
        className={`${FIELD} font-mono text-xl tracking-[0.3em]`}
      />
    </div>
  );
}

/** Seconde étape de la connexion : le code de l'application, ou un code de secours. */
export function VerifyStep({
  challenge,
  onDone,
  onRestart,
}: {
  challenge: string;
  onDone: () => void;
  onRestart: () => void;
}) {
  const recoveryId = useId();
  const [recovery, setRecovery] = useState(false);
  const [code, setCode] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!recovery && code.length !== 6) return setError(MFA_MESSAGES.codeRequired);
    if (recovery && recoveryCode.replace(/[\s-]/g, "").length !== 8) {
      return setError(MFA_MESSAGES.recoveryRequired);
    }
    setBusy(true);
    setError(null);
    try {
      await verifyMfa(challenge, recovery ? { recovery_code: recoveryCode.trim() } : { code });
    } catch (caught) {
      const failure = mfaFailure(caught, recovery);
      setError(failure.message);
      setExpired(failure.expired);
      setBusy(false);
      return;
    }
    onDone();
  }

  if (expired) {
    return (
      <div className="space-y-4">
        <Alert>{MFA_MESSAGES.expired}</Alert>
        <button type="button" onClick={onRestart} className={`${BUTTON.primary} w-full`}>
          Reprendre la connexion
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <p className="flex gap-2">
        <Smartphone aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
        {recovery
          ? "Saisissez un de vos codes de secours. Il ne servira qu'une fois."
          : "Ouvrez votre application d'authentification et saisissez le code affiché pour CoGes Administration."}
      </p>
      {error && <Alert>{error}</Alert>}
      {recovery ? (
        <div className="space-y-1">
          <label htmlFor={recoveryId} className={LABEL}>
            Code de secours
          </label>
          <input
            id={recoveryId}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            placeholder="ABCD-EFGH"
            maxLength={12}
            value={recoveryCode}
            onChange={(event) => setRecoveryCode(event.target.value.toUpperCase())}
            className={`${FIELD} font-mono text-lg tracking-widest`}
          />
        </div>
      ) : (
        <CodeField value={code} onChange={setCode} />
      )}
      <button type="submit" disabled={busy} className={`${BUTTON.primary} w-full`}>
        {busy ? "Vérification…" : "Valider"}
      </button>
      <button
        type="button"
        onClick={() => {
          setRecovery((on) => !on);
          setError(null);
        }}
        className={`${BUTTON.quiet} w-full`}
      >
        <KeyRound aria-hidden="true" className="size-4" />
        {recovery ? "Utiliser le code de l'application" : "Utiliser un code de secours"}
      </button>
      <p className="text-sm text-encre-douce">
        Téléphone perdu et plus de code de secours ? Un autre administrateur peut réinitialiser
        votre double authentification.
      </p>
    </form>
  );
}

/** La clé texte, par groupes de quatre : plus facile à recopier à la main. */
export function groupedKey(secret: string): string {
  return secret.replace(/(.{4})(?=.)/g, "$1 ");
}

/** Enrôlement : application, QR code (ou clé texte), premier code. */
export function EnrollStep({
  challenge,
  onActivated,
  onRestart,
}: {
  challenge: string;
  onActivated: (codes: string[]) => void;
  onRestart: () => void;
}) {
  const keyId = useId();
  const asked = useRef(false);
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Une seule demande : une seconde proposerait un autre secret que celui affiché.
    if (asked.current) return;
    asked.current = true;
    startEnrollment(challenge).then(setEnrollment, (caught: unknown) => {
      const failure = mfaFailure(caught);
      setError(failure.message);
      setExpired(failure.expired || isApiError(caught));
    });
  }, [challenge]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (code.length !== 6) return setError(MFA_MESSAGES.codeRequired);
    setBusy(true);
    setError(null);
    let codes: string[];
    try {
      codes = await confirmEnrollment(challenge, code);
    } catch (caught) {
      const failure = mfaFailure(caught);
      setError(failure.message);
      setExpired(failure.expired);
      setBusy(false);
      return;
    }
    onActivated(codes);
  }

  if (expired) {
    return (
      <div className="space-y-4">
        <Alert>{error ?? MFA_MESSAGES.expired}</Alert>
        <button type="button" onClick={onRestart} className={`${BUTTON.primary} w-full`}>
          Reprendre la connexion
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      <p>
        La double authentification est obligatoire pour l&apos;administration : à chaque connexion,
        votre mot de passe <strong>et</strong> un code de votre téléphone.
      </p>
      <ol className="list-decimal space-y-4 pl-5">
        <li>
          Installez une application d&apos;authentification sur votre téléphone : Google
          Authenticator, Microsoft Authenticator, Aegis ou celle de votre gestionnaire de mots de
          passe.
        </li>
        <li className="space-y-3">
          <span>Dans l&apos;application, ajoutez un compte en scannant ce QR code.</span>
          {enrollment ? (
            <>
              {/* SVG rendu par l'API, fond blanc compris : lisible en clair comme en sombre. */}
              {/* eslint-disable-next-line @next/next/no-img-element -- SVG en ligne */}
              <img
                src={`data:image/svg+xml;utf8,${encodeURIComponent(enrollment.qr_svg)}`}
                alt={`QR code à scanner : compte ${enrollment.account}, ${enrollment.issuer}`}
                width={200}
                height={200}
                className="mx-auto block size-[200px] rounded-lg"
              />
              <div className="space-y-1">
                <p id={keyId} className="text-sm text-encre-douce">
                  Pas d&apos;appareil photo ? Saisissez cette clé dans l&apos;application (type «
                  basé sur le temps ») :
                </p>
                <p
                  aria-describedby={keyId}
                  className="rounded-lg bg-voile px-3 py-2 font-mono text-base break-all select-all"
                >
                  {groupedKey(enrollment.secret)}
                </p>
              </div>
            </>
          ) : (
            !error && <p role="status">Préparation du QR code…</p>
          )}
        </li>
        <li className="space-y-3">
          <span>Saisissez le code à 6 chiffres que l&apos;application affiche.</span>
          {error && <Alert>{error}</Alert>}
          <CodeField value={code} onChange={setCode} />
        </li>
      </ol>
      <button type="submit" disabled={busy || !enrollment} className={`${BUTTON.primary} w-full`}>
        {busy ? "Activation…" : "Activer la double authentification"}
      </button>
    </form>
  );
}

/** Les dix codes de secours, montrés une seule fois : à imprimer ou ranger. */
export function RecoveryCodesPanel({
  codes,
  onContinue,
  continueLabel = "Continuer vers l'administration",
}: {
  codes: string[];
  onContinue: () => void;
  continueLabel?: string;
}) {
  const keptId = useId();
  const [kept, setKept] = useState(false);
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-bold">Vos codes de secours</h2>
      <p>
        Si vous perdez votre téléphone, chacun de ces codes remplace <strong>une fois</strong> le
        code de l&apos;application. Ils ne seront plus jamais affichés : imprimez-les ou rangez-les
        dans votre gestionnaire de mots de passe, loin de votre téléphone.
      </p>
      <ol
        aria-label="Codes de secours"
        className="grid grid-cols-2 gap-x-6 gap-y-1 rounded-lg bg-voile px-4 py-3 font-mono text-lg"
      >
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ol>
      <div className="flex flex-wrap gap-2 print:hidden">
        <button type="button" onClick={copy} className={BUTTON.secondary}>
          {copied ? (
            <Check aria-hidden="true" className="size-4" />
          ) : (
            <Copy aria-hidden="true" className="size-4" />
          )}
          {copied ? "Copiés" : "Copier"}
        </button>
        <button type="button" onClick={() => window.print()} className={BUTTON.secondary}>
          <Printer aria-hidden="true" className="size-4" />
          Imprimer
        </button>
      </div>
      <div className="flex items-start gap-3 print:hidden">
        <input
          id={keptId}
          type="checkbox"
          checked={kept}
          onChange={(event) => setKept(event.target.checked)}
          className="mt-1 size-5 shrink-0"
        />
        <label htmlFor={keptId}>J&apos;ai rangé ces codes en lieu sûr.</label>
      </div>
      <button
        type="button"
        disabled={!kept}
        onClick={onContinue}
        className={`${BUTTON.primary} w-full print:hidden`}
      >
        {continueLabel}
      </button>
    </div>
  );
}
