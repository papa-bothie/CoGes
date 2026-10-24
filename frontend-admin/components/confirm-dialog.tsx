"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";

import { BUTTON, FIELD, LABEL } from "@/components/ui";

export type ConfirmRequest = {
  /** Titre qui nomme la cible : « Suspendre Moussa B. ? ». */
  title: string;
  /** La conséquence, en mots simples. */
  consequence: ReactNode;
  /** L'étiquette du bouton, explicite : « Suspendre Moussa B. », jamais « OK ». */
  confirmLabel: string;
  /** Action destructrice : bouton rouge, « Annuler » préfocalisé. */
  destructive?: boolean;
  /** Raison obligatoire (3 caractères au moins), gardée au journal. */
  requireReason?: boolean;
  /** Reçoit la raison (vide sans raison demandée) ; lève une erreur lisible en cas d'échec. */
  onConfirm: (reason: string) => Promise<void>;
};

/**
 * Confirmation unique des actions sensibles (prompt 27, D5) : Échap annule, le focus revient
 * au bouton d'origine, le bouton se désactive pendant l'appel (pas de double envoi).
 */
export function ConfirmDialog({
  request,
  onClose,
}: {
  request: ConfirmRequest | null;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const bodyId = useId();
  const reasonId = useId();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (request && !dialog.open) {
      opener.current = document.activeElement as HTMLElement | null;
      setReason("");
      setError(null);
      setBusy(false);
      dialog.showModal?.();
      dialog.setAttribute("open", "");
      const first = request.destructive
        ? cancelRef.current
        : request.requireReason
          ? reasonRef.current
          : confirmRef.current;
      first?.focus();
    }
    if (!request && dialog.open) {
      dialog.close?.();
      dialog.removeAttribute("open");
      opener.current?.focus();
    }
  }, [request]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!request || busy) return;
    if (request.requireReason && reason.trim().length < 3) {
      setError("Donnez la raison (3 caractères au moins) : elle est gardée au journal.");
      reasonRef.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await request.onConfirm(reason.trim());
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "L'action n'a pas abouti. Réessayez.");
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-2xl border border-trait bg-surface p-0 text-encre backdrop:bg-ombre/50"
    >
      {request && (
        <form onSubmit={submit} className="space-y-4 p-6">
          <h2 id={titleId} className="text-xl font-bold">
            {request.title}
          </h2>
          <div id={bodyId} className="text-encre-douce">
            {request.consequence}
          </div>
          {request.requireReason && (
            <div className="space-y-1">
              <label htmlFor={reasonId} className={LABEL}>
                Raison
              </label>
              <textarea
                id={reasonId}
                ref={reasonRef}
                value={reason}
                maxLength={500}
                rows={3}
                onChange={(event) => setReason(event.target.value)}
                className={FIELD}
              />
            </div>
          )}
          {error && (
            <p role="alert" className="rounded-lg bg-danger-teinte px-3 py-2 text-danger">
              {error}
            </p>
          )}
          <div className="flex flex-wrap justify-end gap-2">
            <button
              ref={cancelRef}
              type="button"
              onClick={onClose}
              disabled={busy}
              className={BUTTON.secondary}
            >
              Annuler
            </button>
            <button
              ref={confirmRef}
              type="submit"
              disabled={busy}
              aria-busy={busy}
              className={request.destructive ? BUTTON.danger : BUTTON.primary}
            >
              {busy ? "Un instant…" : request.confirmLabel}
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
}
