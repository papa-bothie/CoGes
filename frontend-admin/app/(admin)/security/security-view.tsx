"use client";

import { ShieldCheck } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { CodeField, MFA_MESSAGES, RecoveryCodesPanel, mfaFailure } from "@/components/mfa-steps";
import { BUTTON, Card, Notice, PageHeader, Skeleton } from "@/components/ui";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { PlatformMe } from "@/lib/api/schema";
import { formatDateTime } from "@/lib/format";

/**
 * « Ma sécurité » (ADR 0105) : l'état de sa double authentification et ses codes de
 * secours. Régénérer exige un code de l'application ; les nouveaux codes ne sont montrés
 * qu'une fois, et les anciens ne servent plus.
 */
export function SecurityView() {
  const [me, setMe] = useState<PlatformMe | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [asking, setAsking] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    unwrap(api.GET("/api/v1/platform/auth/me")).then(setMe, (caught: unknown) =>
      setError(errorMessage(caught)),
    );
  }, [version]);

  async function regenerate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (code.length !== 6) return setError(MFA_MESSAGES.codeRequired);
    setBusy(true);
    setError(null);
    try {
      const result = await unwrap(
        api.POST("/api/v1/platform/auth/mfa/recovery-codes", { body: { code } }),
      );
      setCodes(result.recovery_codes);
      setAsking(false);
      setCode("");
    } catch (caught) {
      setError(mfaFailure(caught).message);
    } finally {
      setBusy(false);
    }
  }

  if (codes) {
    return (
      <section aria-labelledby="titre-securite" className="max-w-xl space-y-5">
        <PageHeader id="titre-securite" title="Ma sécurité" />
        <Card>
          <RecoveryCodesPanel
            codes={codes}
            continueLabel="Terminé"
            onContinue={() => {
              setCodes(null);
              setDone(true);
              setVersion((value) => value + 1);
            }}
          />
        </Card>
      </section>
    );
  }

  return (
    <section aria-labelledby="titre-securite" className="max-w-xl space-y-5">
      <PageHeader
        id="titre-securite"
        title="Ma sécurité"
        description="Votre double authentification et vos codes de secours."
      />
      {done && <Notice tone="succes">Nouveaux codes de secours enregistrés.</Notice>}
      {!me && !error && <Skeleton label="Chargement" />}
      {me && (
        <Card aria-labelledby="titre-double" className="space-y-4">
          <h2 id="titre-double" className="flex items-center gap-2 text-lg font-bold">
            <ShieldCheck aria-hidden="true" className="size-5 text-succes" />
            Double authentification active
          </h2>
          {me.mfa_enabled_at && (
            <p>Activée le {formatDateTime(me.mfa_enabled_at)}, avec votre application.</p>
          )}
          <p>
            Codes de secours encore utilisables : <strong>{me.recovery_codes_left}</strong> sur 10.
            {me.recovery_codes_left <= 3 && " Pensez à en générer de nouveaux."}
          </p>
          {error && <Notice tone="danger">{error}</Notice>}
          {asking ? (
            <form onSubmit={regenerate} noValidate className="space-y-3">
              <CodeField
                value={code}
                onChange={setCode}
                label="Code de votre application"
                hint="Pour confirmer que c'est bien vous. Les anciens codes de secours ne serviront plus."
              />
              <div className="flex flex-wrap gap-2">
                <button type="submit" disabled={busy} className={BUTTON.primary}>
                  {busy ? "Génération…" : "Générer de nouveaux codes"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setAsking(false);
                    setError(null);
                  }}
                  className={BUTTON.quiet}
                >
                  Annuler
                </button>
              </div>
            </form>
          ) : (
            <button
              type="button"
              onClick={() => {
                setAsking(true);
                setDone(false);
              }}
              className={BUTTON.secondary}
            >
              Générer de nouveaux codes de secours
            </button>
          )}
          <p className="text-sm text-encre-douce">
            Téléphone perdu ou changé ? Demandez à un autre administrateur de réinitialiser votre
            double authentification : vous l&apos;enrôlerez à nouveau à la connexion suivante.
          </p>
        </Card>
      )}
      {!me && error && <Notice tone="danger">{error}</Notice>}
    </section>
  );
}
