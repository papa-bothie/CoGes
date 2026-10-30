"use client";

import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";

import { EnrollStep, RecoveryCodesPanel } from "@/components/mfa-steps";
import { BUTTON, FIELD, LABEL } from "@/components/ui";
import { isApiError } from "@/lib/api/errors";
import { acceptInvitation, loginUrl } from "@/lib/auth/session";

export const MIN_PASSWORD = 12;
const INVALID =
  "Ce lien d'invitation n'est plus valable. Demandez à un administrateur de vous en envoyer un nouveau.";

/**
 * Le mot de passe, puis l'enrôlement de la double authentification (ADR 0105) et les
 * codes de secours : aucune session avant le premier code juste.
 */
export function AcceptInvitation({ token }: { token: string }) {
  const router = useRouter();
  const [challenge, setChallenge] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  if (codes) return <RecoveryCodesPanel codes={codes} onContinue={() => router.replace("/")} />;
  if (challenge) {
    return (
      <EnrollStep
        challenge={challenge}
        onActivated={setCodes}
        // Le compte existe désormais : la suite passe par la connexion ordinaire.
        onRestart={() => router.replace(loginUrl())}
      />
    );
  }
  return <ChoosePassword token={token} onAccepted={setChallenge} />;
}

/** La règle est affichée **avant** toute erreur ; un lien invalide a un seul message. */
function ChoosePassword({
  token,
  onAccepted,
}: {
  token: string;
  onAccepted: (challenge: string) => void;
}) {
  const passwordId = useId();
  const confirmId = useId();
  const ruleId = useId();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password.length < MIN_PASSWORD) {
      setError(`Le mot de passe doit compter ${MIN_PASSWORD} caractères au moins.`);
      return;
    }
    if (password !== confirmation) {
      setError("Les deux mots de passe ne sont pas identiques.");
      return;
    }
    setBusy(true);
    setError(null);
    let challenge: string;
    try {
      challenge = (await acceptInvitation(token, password)).challenge_token;
    } catch (caught) {
      setError(
        isApiError(caught) && caught.code === "invitation_invalid"
          ? INVALID
          : isApiError(caught)
            ? caught.message
            : "Le service ne répond pas. Réessayez dans un instant.",
      );
      setBusy(false);
      return;
    }
    onAccepted(challenge);
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <p id={ruleId} className="rounded-lg bg-voile px-3 py-2">
        Règle : {MIN_PASSWORD} caractères au moins. Une phrase de plusieurs mots est plus sûre et
        plus facile à retenir.
      </p>
      {error && (
        <p role="alert" className="rounded-lg bg-danger-teinte px-3 py-2 font-semibold text-danger">
          {error}
        </p>
      )}
      <div className="space-y-1">
        <label htmlFor={passwordId} className={LABEL}>
          Mot de passe
        </label>
        <input
          id={passwordId}
          type="password"
          autoComplete="new-password"
          aria-describedby={ruleId}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className={FIELD}
        />
      </div>
      <div className="space-y-1">
        <label htmlFor={confirmId} className={LABEL}>
          Le même, une seconde fois
        </label>
        <input
          id={confirmId}
          type="password"
          autoComplete="new-password"
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
          className={FIELD}
        />
      </div>
      <button type="submit" disabled={busy} className={`${BUTTON.primary} w-full`}>
        {busy ? "Création…" : "Continuer"}
      </button>
    </form>
  );
}
