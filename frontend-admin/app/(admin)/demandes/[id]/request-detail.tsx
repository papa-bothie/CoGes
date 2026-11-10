"use client";

import { ArrowLeft, MessageCircle, Phone } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useState } from "react";

import { useMe } from "@/components/admin-shell";
import { ConfirmDialog, type ConfirmRequest } from "@/components/confirm-dialog";
import { BUTTON, Card, FIELD, LABEL, Notice, Pill } from "@/components/ui";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { SignupRequestRead } from "@/lib/api/schema";
import { formatDateTime } from "@/lib/format";
import {
  REJECT_REASONS,
  accessMessage,
  age,
  firstContactMessage,
  phoneDigits,
  rejectLabel,
  requestState,
  whatsappLink,
} from "@/lib/signup";

type RejectReason = (typeof REJECT_REASONS)[number]["value"];

export function RequestDetail({
  requestId,
  merchantUrl,
}: {
  requestId: string;
  merchantUrl: string;
}) {
  const me = useMe();
  const isAdmin = me?.role === "administrator";
  const [request, setRequest] = useState<SignupRequestRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    unwrap(
      api.GET("/api/v1/platform/signup-requests/{request_id}", {
        params: { path: { request_id: requestId } },
      }),
    ).then(
      (loaded) => {
        setRequest(loaded);
        setMessage(
          loaded.status === "activated" && loaded.company_slug
            ? accessMessage(loaded.company_slug, merchantUrl)
            : firstContactMessage(loaded),
        );
      },
      (caught: unknown) => setError(errorMessage(caught)),
    );
  }, [requestId, merchantUrl]);

  if (error && !request) return <Notice tone="danger">{error}</Notice>;
  if (!request) return <p aria-live="polite">Chargement…</p>;

  const state = requestState(request);
  const pending = request.status === "pending";
  const title = request.shop_name ?? "Demande effacée";

  function activate() {
    setNotice(null);
    setConfirm({
      title: `Ouvrir « ${title} » ?`,
      consequence: (
        <p>
          La boutique est créée avec son gérant et le mot de passe qu&apos;il a choisi ; ses 30
          jours d&apos;essai commencent maintenant. Envoyez-lui ensuite l&apos;accès sur WhatsApp.
        </p>
      ),
      confirmLabel: `Ouvrir « ${title} »`,
      onConfirm: async () => {
        const updated = await unwrap(
          api.POST("/api/v1/platform/signup-requests/{request_id}/activate", {
            params: { path: { request_id: requestId } },
          }),
        );
        setRequest(updated);
        if (updated.company_slug) setMessage(accessMessage(updated.company_slug, merchantUrl));
        setNotice(`La boutique est ouverte. Code : ${updated.company_slug ?? ""}.`);
      },
    });
  }

  return (
    <section aria-labelledby="titre-demande" className="space-y-6">
      <Link
        href="/demandes"
        className="inline-flex min-h-11 items-center gap-1.5 text-encre-douce underline"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        Demandes
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 id="titre-demande" className="text-2xl font-bold tracking-tight">
          {title}
        </h1>
        <Pill tone={state.tone}>{state.label}</Pill>
      </div>
      {notice && <Notice tone="succes">{notice}</Notice>}
      {error && <Notice tone="danger">{error}</Notice>}

      {(request.known_accounts ?? []).length > 0 && (
        <Notice tone="attention">
          Déjà connu :{" "}
          {(request.known_accounts ?? []).map((known, index) => (
            <span key={known.company_id}>
              {index > 0 && ", "}
              <Link href={`/companies/${known.company_id}`} className="font-semibold underline">
                {known.company_name}
              </Link>{" "}
              ({known.matched_on === "phone" ? "même numéro" : "même e-mail"})
            </span>
          ))}
          . Vérifiez avant d&apos;ouvrir une seconde boutique.
        </Notice>
      )}

      <Card aria-label="La demande">
        <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-3">
          <Info label="Nom" value={request.full_name} />
          <Info label="Téléphone" value={request.phone} />
          <Info
            label="E-mail"
            value={
              request.email
                ? `${request.email}${request.email_verified_at ? " (vérifié)" : " (non vérifié)"}`
                : "Aucun"
            }
          />
          <Info
            label="Reçue"
            value={`${formatDateTime(request.created_at)} (il y a ${age(request.created_at)})`}
          />
          <Info label="Conditions acceptées" value={`version du ${request.legal_version}`} />
          {request.status === "activated" && (
            <Info label="Code de la boutique" value={request.company_slug} />
          )}
          {request.status === "rejected" && (
            <Info label="Raison du refus" value={rejectLabel(request.reject_reason)} />
          )}
          {request.decided_at && (
            <Info label="Décidée" value={formatDateTime(request.decided_at)} />
          )}
        </dl>
      </Card>

      {!request.purged && request.phone && (
        <Card aria-labelledby="contacter">
          <h2 id="contacter" className="text-lg font-bold">
            {request.status === "activated" ? "Envoyer l'accès" : "Contacter"}
          </h2>
          <label htmlFor="message-whatsapp" className={`${LABEL} mt-3`}>
            Message WhatsApp (modifiable)
          </label>
          <textarea
            id="message-whatsapp"
            rows={4}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            className={`${FIELD} mt-1 min-h-28 py-2`}
          />
          {request.status === "activated" && (
            <p className="mt-1 text-sm text-encre-douce">
              Jamais le mot de passe : il l&apos;a choisi lui-même.
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <a
              href={whatsappLink(request.phone, message)}
              target="_blank"
              rel="noopener noreferrer"
              className={`${BUTTON.primary} inline-flex items-center gap-2`}
            >
              <MessageCircle aria-hidden="true" className="size-4" />
              {request.status === "activated"
                ? "Envoyer l'accès sur WhatsApp"
                : "Écrire sur WhatsApp"}
            </a>
            <a
              href={`tel:+${phoneDigits(request.phone)}`}
              className={`${BUTTON.secondary} inline-flex items-center gap-2`}
            >
              <Phone aria-hidden="true" className="size-4" />
              Appeler
            </a>
          </div>
        </Card>
      )}

      {isAdmin && !request.purged && (
        <NoteCard
          request={request}
          onSaved={(updated) => (setRequest(updated), setNotice("Note enregistrée."))}
        />
      )}

      {isAdmin && pending && (
        <div className="flex flex-wrap gap-3">
          <button type="button" onClick={activate} className={BUTTON.primary}>
            Ouvrir la boutique
          </button>
          <RejectForm
            requestId={requestId}
            onDone={(updated) => (setRequest(updated), setNotice("La demande est refusée."))}
            onError={setError}
          />
        </div>
      )}

      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </section>
  );
}

function Info({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-sm text-encre-douce">{label}</dt>
      <dd className="font-semibold break-words">{value || "—"}</dd>
    </div>
  );
}

function NoteCard({
  request,
  onSaved,
}: {
  request: SignupRequestRead;
  onSaved: (updated: SignupRequestRead) => void;
}) {
  const id = useId();
  const [note, setNote] = useState(request.team_note ?? "");
  const [saving, setSaving] = useState(false);
  return (
    <Card aria-labelledby={`${id}-titre`}>
      <h2 id={`${id}-titre`} className="text-lg font-bold">
        Note de l&apos;équipe
      </h2>
      <form
        className="mt-3 space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!note.trim()) return;
          setSaving(true);
          unwrap(
            api.PUT("/api/v1/platform/signup-requests/{request_id}/note", {
              params: { path: { request_id: request.id } },
              body: { note: note.trim() },
            }),
          )
            .then(onSaved)
            .finally(() => setSaving(false));
        }}
      >
        <label htmlFor={id} className="sr-only">
          Note de l&apos;équipe
        </label>
        <textarea
          id={id}
          rows={3}
          maxLength={1000}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Appelé lundi, rappeler jeudi…"
          className={`${FIELD} min-h-24 py-2`}
        />
        <button type="submit" disabled={saving || !note.trim()} className={BUTTON.secondary}>
          Enregistrer la note
        </button>
      </form>
    </Card>
  );
}

function RejectForm({
  requestId,
  onDone,
  onError,
}: {
  requestId: string;
  onDone: (updated: SignupRequestRead) => void;
  onError: (message: string) => void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<RejectReason>("unreachable");
  const [note, setNote] = useState("");
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className={BUTTON.danger}>
        Refuser la demande
      </button>
    );
  }
  return (
    <form
      aria-label="Refuser la demande"
      className="w-full space-y-3 rounded-xl border border-trait bg-surface p-4"
      onSubmit={(event) => {
        event.preventDefault();
        unwrap(
          api.POST("/api/v1/platform/signup-requests/{request_id}/reject", {
            params: { path: { request_id: requestId } },
            body: { reason, note: note.trim() || null },
          }),
        ).then(onDone, (caught: unknown) => onError(errorMessage(caught)));
      }}
    >
      <div className="space-y-1">
        <label htmlFor={`${id}-raison`} className={LABEL}>
          Raison
        </label>
        <select
          id={`${id}-raison`}
          value={reason}
          onChange={(event) => setReason(event.target.value as RejectReason)}
          className={FIELD}
        >
          {REJECT_REASONS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-1">
        <label htmlFor={`${id}-note`} className={LABEL}>
          Note (facultative)
        </label>
        <textarea
          id={`${id}-note`}
          rows={2}
          maxLength={1000}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          className={`${FIELD} min-h-20 py-2`}
        />
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={BUTTON.danger}>
          Refuser définitivement
        </button>
        <button type="button" onClick={() => setOpen(false)} className={BUTTON.secondary}>
          Annuler
        </button>
      </div>
    </form>
  );
}
