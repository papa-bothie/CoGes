"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Truck, UserRound } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

import { FieldError } from "@/components/field-error";
import { fieldClasses, RUBRIQUE_CLASSES } from "@/components/kit/rubrique";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";
import { formatPhone, isCompletePhone } from "@/lib/phone";
import { cn } from "@/lib/utils";

export type PersonKind = "customer" | "supplier";
type Customer = Schemas["CustomerRead"];
type Supplier = Schemas["SupplierRead"];
type Saved = { kind: "customer"; person: Customer } | { kind: "supplier"; person: Supplier };

/** Le client en violet, le fournisseur en bleu (maquette 15). */
const RUBRIQUE = { customer: "clients", supplier: "argent" } as const;

/**
 * « Ajouter une personne » (maquette 15) : un client ou un fournisseur, son nom et son
 * téléphone. Le code est attribué par le serveur (ADR 0013) ; encours autorisé et délai de
 * paiement ne se saisissent plus (colonnes nulles = pas de limite). En modification, le
 * genre est fixé et l'e-mail d'un client attend dans « Plus d'infos ».
 */
export function PersonFormDialog({
  open,
  onOpenChange,
  kind: fixedKind,
  initialKind = "customer",
  person,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Genre imposé (fiche, sélecteur de la vente) : les deux boutons disparaissent. */
  kind?: PersonKind;
  initialKind?: PersonKind;
  /** Présent : modification de cette fiche. */
  person?: Customer | Supplier;
  onSaved?: (saved: Saved) => void;
}) {
  const queryClient = useQueryClient();
  const nameId = useId();
  const phoneId = useId();
  const emailId = useId();
  const [kind, setKind] = useState<PersonKind>(fixedKind ?? initialKind);
  const [name, setName] = useState(person?.name ?? "");
  const [phone, setPhone] = useState(formatPhone(person?.phone ?? ""));
  const [email, setEmail] = useState(person && "email" in person ? (person.email ?? "") : "");
  const [phoneError, setPhoneError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const t = labels.people;
  const rubrique = RUBRIQUE[kind];
  const editing = Boolean(person);

  const reset = () => {
    setKind(fixedKind ?? initialKind);
    setName(person?.name ?? "");
    setPhone(formatPhone(person?.phone ?? ""));
    setPhoneError(null);
    setFormError(null);
  };

  const save = useMutation({
    meta: { toastError: false },
    mutationFn: async (): Promise<Saved> => {
      const common = { name: name.trim(), phone: phone || null };
      if (kind === "customer") {
        const body = { ...common, email: email.trim() || null };
        const saved = person
          ? await unwrap(
              api.PATCH("/api/v1/customers/{customer_id}", {
                params: { path: { customer_id: person.id } },
                body,
              }),
            )
          : await unwrap(api.POST("/api/v1/customers", { body }));
        return { kind, person: saved };
      }
      // Un fournisseur n'a pas d'e-mail dans le modèle (§ 8.3).
      const saved = person
        ? await unwrap(
            api.PATCH("/api/v1/suppliers/{supplier_id}", {
              params: { path: { supplier_id: person.id } },
              body: common,
            }),
          )
        : await unwrap(api.POST("/api/v1/suppliers", { body: common }));
      return { kind, person: saved };
    },
    onSuccess: (saved) => {
      const keys = saved.kind === "customer" ? queryKeys.customers : queryKeys.suppliers;
      queryClient.setQueryData(keys.detail(saved.person.id), saved.person);
      void queryClient.invalidateQueries({ queryKey: keys.all });
      toast.success(editing ? t.saved[saved.kind] : t.created[saved.kind]);
      onOpenChange(false);
      onSaved?.(saved);
    },
    onError: (error) => setFormError(errorMessage(error)),
  });

  const submit = () => {
    if (!name.trim()) return;
    if (!isCompletePhone(phone)) {
      setPhoneError(t.phoneIncomplete);
      return;
    }
    setPhoneError(null);
    setFormError(null);
    save.mutate();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? t.editTitle[kind] : t.addTitle}</DialogTitle>
        </DialogHeader>
        <form
          noValidate
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          {!fixedKind && !editing && (
            <div role="radiogroup" aria-label={t.kindLabel} className="grid grid-cols-2 gap-2.5">
              {(["customer", "supplier"] as const).map((value) => {
                const Icon = value === "customer" ? UserRound : Truck;
                const picked = kind === value;
                return (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={picked}
                    onClick={() => setKind(value)}
                    className={cn(
                      "flex min-h-bouton items-center justify-center gap-2.5 rounded-bouton border-2 text-libelle transition-colors",
                      "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                      picked
                        ? RUBRIQUE_CLASSES[RUBRIQUE[value]].solid
                        : "border-input bg-card text-foreground hover:bg-voile",
                    )}
                  >
                    <Icon className="size-6" aria-hidden />
                    {t.kind[value]}
                  </button>
                );
              })}
            </div>
          )}

          <div className="space-y-2">
            <label htmlFor={nameId} className="block text-libelle">
              {t.name[kind]}
            </label>
            <input
              id={nameId}
              value={name}
              maxLength={200}
              autoComplete="off"
              onChange={(event) => setName(event.target.value)}
              className={cn(fieldClasses(rubrique), "min-h-bouton px-[18px] text-xl font-semibold")}
            />
          </div>

          <div className="space-y-2">
            <label htmlFor={phoneId} className="block text-libelle">
              {t.phone}
            </label>
            <div className="flex items-stretch gap-2.5">
              <span
                className="flex min-h-bouton items-center rounded-champ border-2 border-input bg-muted px-4 text-xl font-bold numeric text-muted-foreground"
                aria-hidden
              >
                {t.prefix}
              </span>
              <input
                id={phoneId}
                inputMode="tel"
                autoComplete="off"
                placeholder={t.phonePlaceholder}
                value={phone}
                aria-invalid={Boolean(phoneError) || undefined}
                onChange={(event) => setPhone(formatPhone(event.target.value))}
                className={cn(
                  fieldClasses(rubrique),
                  "min-h-bouton px-[18px] text-xl font-semibold numeric",
                )}
              />
            </div>
            <FieldError message={phoneError} />
          </div>

          {editing && kind === "customer" && (
            <details className="rounded-champ border-2 border-input px-4 py-3">
              <summary className="min-h-cible cursor-pointer content-center text-libelle">
                {t.moreInfo}
              </summary>
              <div className="space-y-2 pt-3">
                <label htmlFor={emailId} className="block text-petit font-bold">
                  {t.email}
                </label>
                <input
                  id={emailId}
                  type="email"
                  inputMode="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className={cn(fieldClasses(rubrique), "min-h-cible px-4 text-corps")}
                />
              </div>
            </details>
          )}

          <FieldError message={formError} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {labels.common.close}
            </Button>
            <Button
              type="submit"
              variant={rubrique}
              size="standard"
              disabled={!name.trim() || save.isPending}
            >
              {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t.save[kind]}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
