"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { fieldClasses } from "@/components/kit/rubrique";
import { errorMessage } from "@/lib/api/errors";
import { labels } from "@/lib/labels";
import { resendSignupLink, verifySignupLink, type SignupVerified } from "@/lib/signup/api";
import { cn } from "@/lib/utils";

const t = labels.signup;

type State =
  | { kind: "checking" }
  | { kind: "ready"; slug: string }
  | { kind: "team"; message: string }
  | { kind: "invalid" };

/** Un jeton ne se consomme qu'une fois : un second appel (double effet de React en
 *  développement, double rendu) reprend la même promesse au lieu d'en refaire un. */
const inFlight = new Map<string, Promise<SignupVerified>>();

function verifyOnce(token: string): Promise<SignupVerified> {
  let pending = inFlight.get(token);
  if (!pending) {
    pending = verifySignupLink(token);
    inFlight.set(token, pending);
  }
  return pending;
}

export function VerifyLink({ token }: { token: string | null }) {
  const [state, setState] = useState<State>(token ? { kind: "checking" } : { kind: "invalid" });
  const title = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (!token) return;
    // Le jeton ne reste ni dans l'adresse ni dans l'historique.
    window.history.replaceState(null, "", "/verification");
    let alive = true;
    verifyOnce(token)
      .then((result) => {
        if (!alive) return;
        setState(
          result.status === "ready" && result.company_slug
            ? { kind: "ready", slug: result.company_slug }
            : { kind: "team", message: result.message },
        );
      })
      .catch(() => alive && setState({ kind: "invalid" }));
    return () => {
      alive = false;
    };
  }, [token]);

  useEffect(() => {
    title.current?.focus();
  }, [state.kind]);

  const heading = (text: string) => (
    <h1 ref={title} tabIndex={-1} className="text-[32px] leading-tight font-extrabold outline-none">
      {text}
    </h1>
  );

  if (state.kind === "checking") {
    return (
      <div className="space-y-4" aria-busy="true">
        {heading(t.verifyingTitle)}
        <p role="status" className="text-lg">
          {t.verifying}
        </p>
      </div>
    );
  }
  if (state.kind === "ready") {
    return (
      <div className="space-y-6">
        {heading(t.readyTitle)}
        <p className="text-lg">{t.readyIntro}</p>
        <div className="rounded-carte border-2 border-ventes bg-ventes-teinte p-5">
          <p className="text-mini font-bold tracking-wide text-encre-2 uppercase">{t.shopCode}</p>
          <p className="font-mono text-[26px] font-bold">{state.slug}</p>
        </div>
        <Link
          href={`/login?boutique=${encodeURIComponent(state.slug)}`}
          className="flex min-h-16 w-full items-center justify-center rounded-bouton bg-primary text-xl font-extrabold text-primary-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {t.goLogin}
        </Link>
      </div>
    );
  }
  if (state.kind === "team") {
    return (
      <div className="space-y-6">
        {heading(t.teamTitle)}
        <p className="text-lg">{state.message}</p>
      </div>
    );
  }
  return (
    <div className="space-y-6">
      {heading(t.invalidTitle)}
      <p className="text-lg">{t.invalidIntro}</p>
      <ResendForm />
    </div>
  );
}

function ResendForm() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!email.trim()) return;
        resendSignupLink(email.trim().toLowerCase())
          .then(() => setStatus(t.resent))
          .catch((failure: unknown) => setStatus(errorMessage(failure)));
      }}
    >
      <div className="space-y-2">
        <label htmlFor="renvoi-email" className="block text-libelle">
          {t.invalidEmail}
        </label>
        <input
          id="renvoi-email"
          type="email"
          inputMode="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className={cn(fieldClasses("ventes"), "min-h-[60px] px-[18px] text-[19px]")}
        />
      </div>
      {status && (
        <p role="status" className="rounded-champ bg-voile px-4 py-3 font-semibold">
          {status}
        </p>
      )}
      <button
        type="submit"
        className="flex min-h-bouton w-full items-center justify-center rounded-bouton border-2 border-input bg-card text-libelle font-bold outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {t.invalidResend}
      </button>
    </form>
  );
}
