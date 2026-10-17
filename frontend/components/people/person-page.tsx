"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Truck, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ErrorState } from "@/components/error-state";
import { RUBRIQUE_CLASSES } from "@/components/kit/rubrique";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { withFrom } from "@/lib/back-target";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { labels } from "@/lib/labels";
import { initials } from "@/lib/people";
import { cn } from "@/lib/utils";

import {
  PERSON_RUBRIQUE,
  PersonForm,
  type Customer,
  type PersonKind,
  type SavedPerson,
  type Supplier,
} from "./person-form";

const t = labels.people;
const PATH = { customer: "/customers", supplier: "/suppliers" } as const;

/**
 * « Ajouter une personne », maquette v2 (écran 15) : client ou fournisseur en deux grandes
 * tuiles, le nom et le téléphone dans une carte, puis un écran de succès (« Ajouter
 * quelqu'un d'autre », « Faire une vente »). Ouvert depuis une liste, le genre est déjà
 * choisi ; il reste modifiable avant d'enregistrer.
 */
export function NewPersonPage({ initialKind }: { initialKind: PersonKind }) {
  const [kind, setKind] = useState<PersonKind>(initialKind);
  const [saved, setSaved] = useState<SavedPerson | null>(null);
  const [round, setRound] = useState(0);

  return (
    <div className="mx-auto flex max-w-[592px] flex-col gap-5">
      <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.addTitle}</h1>
      <div role="radiogroup" aria-label={t.kindLabel} className="flex flex-wrap gap-3">
        {(["customer", "supplier"] as const).map((value) => {
          const Icon = value === "customer" ? UserRound : Truck;
          const picked = kind === value;
          return (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={picked}
              onClick={() => {
                setKind(value);
                setSaved(null);
              }}
              className={cn(
                "flex min-h-[84px] flex-[1_1_200px] items-center justify-center gap-3 rounded-[20px] border-2 text-[19px] font-extrabold",
                "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                picked
                  ? RUBRIQUE_CLASSES[PERSON_RUBRIQUE[value]].picked
                  : "border-input bg-card text-encre-2 hover:bg-voile",
              )}
            >
              <Icon className="size-7" aria-hidden />
              {t.kind[value]}
            </button>
          );
        })}
      </div>

      {saved ? (
        <SavedCard
          saved={saved}
          onAgain={() => {
            setSaved(null);
            setRound((value) => value + 1);
          }}
        />
      ) : (
        <section className="rounded-carte border border-border bg-card p-6">
          <PersonForm key={`${kind}-${round}`} kind={kind} onSaved={setSaved} />
        </section>
      )}
    </div>
  );
}

function SavedCard({ saved, onAgain }: { saved: SavedPerson; onAgain: () => void }) {
  const rubrique = PERSON_RUBRIQUE[saved.kind];
  const { person } = saved;
  const next =
    saved.kind === "customer"
      ? { href: `/sales/new?customer=${person.id}`, label: t.sell }
      : {
          href: withFrom(`/inventory/receive?supplier=${person.id}`, `/suppliers/${person.id}`),
          label: t.receive,
        };
  return (
    <section
      aria-live="polite"
      className="flex flex-col items-center gap-3 rounded-carte border border-border bg-card px-6 py-9 text-center"
    >
      <span
        aria-hidden
        className={cn(
          "flex size-[84px] items-center justify-center rounded-full text-[28px] font-extrabold",
          RUBRIQUE_CLASSES[rubrique].solid,
        )}
      >
        {initials(person.name)}
      </span>
      <h2 className="text-[26px] leading-tight font-extrabold">{person.name}</h2>
      {person.phone && <p className="text-lg numeric text-muted-foreground">{person.phone}</p>}
      <p className={cn("text-lg font-bold", RUBRIQUE_CLASSES[rubrique].ink)}>
        {t.savedLine[saved.kind]}
      </p>
      <div className="mt-2 flex flex-wrap justify-center gap-3">
        <Button type="button" variant={rubrique} size="standard" onClick={onAgain}>
          {t.again}
        </Button>
        <Button asChild variant="secondaire" size="standard">
          <Link href={next.href}>{next.label}</Link>
        </Button>
      </div>
    </section>
  );
}

/** « Modifier » d'une fiche (écran 15 en modification) : retour à la fiche une fois enregistré. */
export function EditPersonPage({ kind, id }: { kind: PersonKind; id: string }) {
  const router = useRouter();
  const person = useQuery({
    queryKey: (kind === "customer" ? queryKeys.customers : queryKeys.suppliers).detail(id),
    queryFn: (): Promise<Customer | Supplier> =>
      kind === "customer"
        ? unwrap(
            api.GET("/api/v1/customers/{customer_id}", {
              params: { path: { customer_id: id } },
            }),
          )
        : unwrap(
            api.GET("/api/v1/suppliers/{supplier_id}", {
              params: { path: { supplier_id: id } },
            }),
          ),
  });

  return (
    <div className="mx-auto flex max-w-[592px] flex-col gap-5">
      <Link
        href={`${PATH[kind]}/${id}`}
        className="inline-flex min-h-11 items-center gap-2 self-start font-bold text-foreground hover:underline pointer-coarse:min-h-12"
      >
        <ArrowLeft className="size-[22px]" aria-hidden />
        {person.data?.name ?? t.back[kind]}
      </Link>
      <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.editTitle[kind]}</h1>
      {person.isError ? (
        <ErrorState error={person.error} onRetry={() => void person.refetch()} />
      ) : !person.data ? (
        <Skeleton className="h-72 w-full rounded-carte" />
      ) : (
        <section className="rounded-carte border border-border bg-card p-6">
          <PersonForm
            kind={kind}
            person={person.data}
            onSaved={() => router.push(`${PATH[kind]}/${id}`)}
          />
        </section>
      )}
    </div>
  );
}
