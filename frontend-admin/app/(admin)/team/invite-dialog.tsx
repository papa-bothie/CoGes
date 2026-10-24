"use client";

import { Copy } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { BUTTON, FIELD, LABEL } from "@/components/ui";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { InvitationIssued } from "@/lib/api/schema";

/** Ce que chaque profil permet, dit en une phrase au moment d'inviter. */
export const PROFILE_HINTS: Record<string, string> = {
  support:
    "Support : consulte les entreprises, les comptes, les statistiques et le système, ouvre un accès support en lecture seule ; ne modifie ni l'équipe ni les abonnements.",
  administrator:
    "Administrateur : tout ce que fait le support, plus gérer l'équipe, suspendre une entreprise, changer une offre, enregistrer un paiement et lire le journal.",
};

/**
 * Inviter un collègue (prompt 27, D1.3) : nom, e-mail, profil, un bouton. Le bouton dit ce
 * qui part (confirmation légère). La clé d'idempotence est gardée jusqu'au succès : un
 * double clic ou un nouvel essai n'envoie pas deux e-mails.
 */
export function InviteDialog({
  open,
  onClose,
  onInvited,
}: {
  open: boolean;
  onClose: () => void;
  onInvited: (issued: InvitationIssued) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const nameId = useId();
  const emailId = useId();
  const roleId = useId();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("support");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement as HTMLElement | null;
      setName("");
      setEmail("");
      setRole("support");
      setError(null);
      setBusy(false);
      key.current = null;
      dialog.showModal?.();
      dialog.setAttribute("open", "");
      nameRef.current?.focus();
    }
    if (!open && dialog.open) {
      dialog.close?.();
      dialog.removeAttribute("open");
      opener.current?.focus();
    }
  }, [open]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!name.trim() || !email.trim()) {
      setError("Donnez le nom et l'adresse e-mail du collègue.");
      return;
    }
    key.current ??= crypto.randomUUID();
    setBusy(true);
    setError(null);
    try {
      const issued = await unwrap(
        api.POST("/api/v1/platform/team/invitations", {
          params: { header: { "Idempotency-Key": key.current } },
          body: {
            display_name: name.trim(),
            email: email.trim(),
            role: role === "administrator" ? "administrator" : "support",
          },
        }),
      );
      key.current = null;
      onInvited(issued);
    } catch (caught) {
      setError(errorMessage(caught));
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-2xl border border-trait bg-surface p-0 text-encre backdrop:bg-ombre/50"
    >
      <form onSubmit={submit} noValidate className="space-y-4 p-6">
        <h2 id={titleId} className="text-xl font-bold">
          Inviter un collègue
        </h2>
        <div className="space-y-1">
          <label htmlFor={nameId} className={LABEL}>
            Nom
          </label>
          <input
            id={nameId}
            ref={nameRef}
            value={name}
            maxLength={120}
            autoComplete="off"
            onChange={(event) => setName(event.target.value)}
            className={FIELD}
          />
        </div>
        <div className="space-y-1">
          <label htmlFor={emailId} className={LABEL}>
            E-mail
          </label>
          <input
            id={emailId}
            type="email"
            value={email}
            maxLength={254}
            autoComplete="off"
            onChange={(event) => setEmail(event.target.value)}
            className={FIELD}
          />
        </div>
        <div className="space-y-1">
          <label htmlFor={roleId} className={LABEL}>
            Profil
          </label>
          <select
            id={roleId}
            value={role}
            onChange={(event) => setRole(event.target.value)}
            aria-describedby={`${roleId}-aide`}
            className={FIELD}
          >
            <option value="support">Support</option>
            <option value="administrator">Administrateur</option>
          </select>
          <p id={`${roleId}-aide`} className="text-sm text-encre-douce">
            {PROFILE_HINTS[role]}
          </p>
        </div>
        {error && (
          <p role="alert" className="rounded-lg bg-danger-teinte px-3 py-2 text-danger">
            {error}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={onClose} disabled={busy} className={BUTTON.secondary}>
            Annuler
          </button>
          <button type="submit" disabled={busy} aria-busy={busy} className={BUTTON.primary}>
            {busy ? "Envoi…" : "Envoyer l'invitation"}
          </button>
        </div>
        <p className="text-sm text-encre-douce">Le lien est valable 72 heures, une seule fois.</p>
      </form>
    </dialog>
  );
}

/** Sans SMTP, le lien est montré **une fois** : à copier et transmettre soi-même. */
export function InvitationLink({ url, email }: { url: string; email: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div
      role="status"
      className="space-y-2 rounded-lg bg-attention-teinte px-4 py-3 text-attention"
    >
      <p className="font-semibold">
        E-mail non configuré : aucun message n&apos;est parti vers {email}.
      </p>
      <p>Copiez ce lien et transmettez-le vous-même. Il ne sera plus affiché.</p>
      <div className="flex flex-wrap items-center gap-2">
        <code className="min-w-0 flex-1 rounded bg-surface px-2 py-1 text-sm break-all text-encre">
          {url}
        </code>
        <button
          type="button"
          onClick={() =>
            void navigator.clipboard?.writeText(url).then(
              () => setCopied(true),
              () => setCopied(false),
            )
          }
          className={BUTTON.secondary}
        >
          <Copy aria-hidden="true" className="size-4" />
          {copied ? "Lien copié" : "Copier le lien"}
        </button>
      </div>
    </div>
  );
}
