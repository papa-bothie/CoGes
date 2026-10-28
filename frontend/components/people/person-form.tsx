"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Truck, UserRound } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { DraftBanner } from "@/components/draft-banner";
import { FieldError } from "@/components/field-error";
import { fieldClasses, RUBRIQUE_CLASSES } from "@/components/kit/rubrique";
import { Button } from "@/components/ui/button";
import { useDraft } from "@/hooks/use-draft";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import { draftOneOf, draftString } from "@/lib/drafts";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";
import { formatPhone, isCompletePhone } from "@/lib/phone";
import { cn } from "@/lib/utils";

export type PersonKind = "customer" | "supplier";
export type Customer = Schemas["CustomerRead"];
export type Supplier = Schemas["SupplierRead"];
export type SavedPerson =
  { kind: "customer"; person: Customer } | { kind: "supplier"; person: Supplier };

/** Le client en violet, le fournisseur en bleu (maquette 15). */
export const PERSON_RUBRIQUE = { customer: "clients", supplier: "argent" } as const;

/**
 * Le formulaire « Ajouter une personne » (maquette 15), partagé par la page et la fenêtre
 * de la vente et de la livraison : un client ou un fournisseur, son nom et son téléphone.
 * Le code est attribué par le serveur (ADR 0013). En modification, le genre est fixé ;
 * l'e-mail d'un client et l'adresse d'un fournisseur attendent dans « Plus d'infos ».
 */
export function PersonForm({
  kind: fixedKind,
  initialKind = "customer",
  person,
  onSaved,
  actions,
  className,
}: {
  /** Genre imposé : les deux boutons disparaissent. */
  kind?: PersonKind;
  initialKind?: PersonKind;
  /** Présent : modification de cette fiche. */
  person?: Customer | Supplier;
  onSaved?: (saved: SavedPerson) => void;
  /** Boutons placés avant « Enregistrer » (« Fermer » dans la fenêtre). */
  actions?: ReactNode;
  className?: string;
}) {
  const queryClient = useQueryClient();
  const nameId = useId();
  const phoneId = useId();
  const moreId = useId();
  const [chosenKind, setKind] = useState<PersonKind>(initialKind);
  // Un genre imposé (fiche, vente, ou la page qui le choisit hors du formulaire) l'emporte.
  const kind = fixedKind ?? chosenKind;
  const [name, setName] = useState(person?.name ?? "");
  const [phone, setPhone] = useState(formatPhone(person?.phone ?? ""));
  const [email, setEmail] = useState(person && "email" in person ? (person.email ?? "") : "");
  const [address, setAddress] = useState(
    person && "address" in person ? (person.address ?? "") : "",
  );
  const [phoneError, setPhoneError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  // Brouillon d'une fiche client ou fournisseur (ADR 0101), un par fiche modifiée.
  const draft = useDraft(
    {
      formId: person ? `person-${kind}` : "person-new",
      version: 1,
      fields: ["kind", "name", "phone", "email", "address"],
      meaningful: ["name", "phone", "email", "address"],
      objectId: person?.id,
    },
    { kind: fixedKind || person ? "" : chosenKind, name, phone, email, address },
    (fields) => {
      const savedKind = draftOneOf(fields.kind, ["customer", "supplier"] as const);
      if (savedKind && !fixedKind && !person) setKind(savedKind);
      setName(draftString(fields.name) ?? "");
      setPhone(draftString(fields.phone) ?? "");
      setEmail(draftString(fields.email) ?? "");
      setAddress(draftString(fields.address) ?? "");
    },
  );
  const t = labels.people;
  const rubrique = PERSON_RUBRIQUE[kind];
  const editing = Boolean(person);

  const save = useMutation({
    meta: { toastError: false },
    mutationFn: async (): Promise<SavedPerson> => {
      const common = { name: name.trim(), phone: phone || null };
      if (kind === "customer") {
        const body = editing ? { ...common, email: email.trim() || null } : common;
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
      const saved = person
        ? await unwrap(
            api.PATCH("/api/v1/suppliers/{supplier_id}", {
              params: { path: { supplier_id: person.id } },
              body: { ...common, address: address.trim() || null },
            }),
          )
        : await unwrap(api.POST("/api/v1/suppliers", { body: common }));
      return { kind, person: saved };
    },
    onSuccess: (saved) => {
      draft.clear();
      const keys = saved.kind === "customer" ? queryKeys.customers : queryKeys.suppliers;
      queryClient.setQueryData(keys.detail(saved.person.id), saved.person);
      void queryClient.invalidateQueries({ queryKey: keys.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.people.all });
      if (editing) toast.success(t.saved[saved.kind]);
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
    <form
      noValidate
      className={cn("space-y-5", className)}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {draft.restored && (
        <DraftBanner
          onClear={() => {
            setName(person?.name ?? "");
            setPhone(formatPhone(person?.phone ?? ""));
            setEmail(person && "email" in person ? (person.email ?? "") : "");
            setAddress(person && "address" in person ? (person.address ?? "") : "");
            draft.clear();
          }}
        />
      )}
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
                    ? RUBRIQUE_CLASSES[PERSON_RUBRIQUE[value]].picked
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
          placeholder={t.namePlaceholder[kind]}
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

      {editing && (
        <details className="rounded-champ border-2 border-input px-4 py-3">
          <summary className="min-h-cible cursor-pointer content-center text-libelle">
            {t.moreInfo}
          </summary>
          <div className="space-y-2 pt-3">
            <label htmlFor={moreId} className="block text-petit font-bold">
              {kind === "customer" ? t.email : t.address}
            </label>
            {kind === "customer" ? (
              <input
                id={moreId}
                type="email"
                inputMode="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className={cn(fieldClasses(rubrique), "min-h-cible px-4 text-corps")}
              />
            ) : (
              <input
                id={moreId}
                value={address}
                maxLength={200}
                placeholder={t.addressPlaceholder}
                onChange={(event) => setAddress(event.target.value)}
                className={cn(fieldClasses(rubrique), "min-h-cible px-4 text-corps")}
              />
            )}
          </div>
        </details>
      )}

      <FieldError message={formError} />
      <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
        {actions}
        <Button
          type="submit"
          variant={rubrique}
          size={actions ? "standard" : "principal"}
          className={cn(!actions && "w-full text-[21px]")}
          disabled={!name.trim() || save.isPending}
        >
          {save.isPending ? (
            <Loader2 className="animate-spin" aria-hidden />
          ) : (
            <Check aria-hidden />
          )}
          {t.save[kind]}
        </Button>
      </div>
    </form>
  );
}
