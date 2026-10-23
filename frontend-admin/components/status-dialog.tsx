"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

export type StatusTarget = "active" | "suspended";

const COPY: Record<StatusTarget, { title: string; body: string; confirm: string }> = {
  suspended: {
    title: "Suspendre l'entreprise ?",
    body: "Personne de cette entreprise ne pourra plus se connecter, et les sessions ouvertes s'arrêteront à la requête suivante. Ses données sont conservées. Le gérant est prévenu par e-mail.",
    confirm: "Suspendre",
  },
  active: {
    title: "Réactiver l'entreprise ?",
    body: "Ses comptes pourront de nouveau se connecter. Le gérant est prévenu par e-mail.",
    confirm: "Réactiver",
  },
};

/**
 * Confirmation obligatoire avant l'appel (action à fort impact) : rien ne part tant que
 * la raison n'est pas donnée et le bouton de confirmation pressé.
 */
export function StatusDialog({
  companyName,
  target,
  open,
  onCancel,
  onConfirm,
}: {
  companyName: string;
  target: StatusTarget;
  open: boolean;
  onCancel: () => void;
  onConfirm: (reason: string) => Promise<void>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const reasonId = useId();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const copy = COPY[target];

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setReason("");
      setError(null);
      dialog.showModal?.();
      dialog.setAttribute("open", "");
    }
    if (!open && dialog.open) {
      dialog.close?.();
      dialog.removeAttribute("open");
    }
  }, [open]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason.trim().length < 3) {
      setError("Donnez la raison (3 caractères au moins) : elle est gardée au journal.");
      return;
    }
    setBusy(true);
    try {
      await onConfirm(reason.trim());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "L'action n'a pas abouti.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-lg border border-trait bg-surface p-0 text-encre backdrop:bg-black/40"
    >
      <form onSubmit={submit} className="space-y-4 p-5">
        <h2 id={titleId} className="text-xl font-bold">
          {copy.title}
        </h2>
        <p>
          <strong>{companyName}</strong> — {copy.body}
        </p>
        <div className="space-y-1">
          <label htmlFor={reasonId} className="block font-semibold">
            Raison
          </label>
          <textarea
            id={reasonId}
            value={reason}
            maxLength={500}
            rows={3}
            onChange={(event) => setReason(event.target.value)}
            className="w-full rounded border border-trait bg-surface px-3 py-2"
          />
        </div>
        {error && (
          <p role="alert" className="rounded bg-danger-teinte px-3 py-2 text-danger">
            {error}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded border border-trait px-4 py-2 font-semibold"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={busy}
            className={`rounded px-4 py-2 font-semibold disabled:opacity-60 ${
              target === "suspended" ? "bg-danger text-surface" : "bg-accent text-accent-encre"
            }`}
          >
            {copy.confirm}
          </button>
        </div>
      </form>
    </dialog>
  );
}
