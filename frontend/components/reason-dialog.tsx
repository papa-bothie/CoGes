"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";

import { FieldError } from "@/components/field-error";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage } from "@/lib/api/errors";
import { labels } from "@/lib/labels";

/** Longueur minimale d'un motif, alignée sur `REASON_MIN_LENGTH` du serveur. */
export const REASON_MIN_LENGTH = 10;

/**
 * Action irréversible qui exige un motif (annulation d'un paiement, abandon de créance).
 * Le motif est vérifié ici pour le confort ; le serveur le revérifie (422).
 */
export function ReasonDialog({
  open,
  onOpenChange,
  title,
  description,
  reasonLabel,
  submitLabel,
  onSubmit,
  pending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  reasonLabel: string;
  submitLabel: string;
  onSubmit: (reason: string) => Promise<unknown>;
  pending: boolean;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const close = (next: boolean) => {
    if (!next) {
      setReason("");
      setError(null);
    }
    onOpenChange(next);
  };

  const submit = async () => {
    if (reason.trim().length < REASON_MIN_LENGTH) {
      setError(labels.validation.reasonTooShort(REASON_MIN_LENGTH));
      return;
    }
    try {
      await onSubmit(reason.trim());
      close(false);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="reason">{reasonLabel}</Label>
            <Textarea
              id="reason"
              value={reason}
              maxLength={500}
              aria-invalid={Boolean(error)}
              onChange={(event) => setReason(event.target.value)}
            />
            <FieldError message={error} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => close(false)}>
              {labels.common.close}
            </Button>
            <Button type="submit" variant="destructive" disabled={pending}>
              {pending && <Loader2 className="animate-spin" aria-hidden />}
              {submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
