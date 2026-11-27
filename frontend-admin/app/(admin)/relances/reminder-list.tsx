"use client";

import { MessageCircle, Phone } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  BUTTON,
  Card,
  EmptyState,
  FIELD,
  LABEL,
  Notice,
  PageHeader,
  Pill,
  Skeleton,
} from "@/components/ui";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { ReminderList as ReminderListData } from "@/lib/api/schema";
import { formatDate, formatDateTime } from "@/lib/format";
import { kindLabel, sentLabel, STAGES, type ReminderItem } from "@/lib/reminders";
import { phoneDigits, whatsappLink } from "@/lib/signup";

/**
 * « À relancer » (ADR 0133) : les boutiques de la veille de leur fin à J+3, et celles
 * mises en pause depuis moins de 7 jours. La routine du matin pour les commerçants sans
 * e-mail : le message de l'étape, prérempli et modifiable, part par un lien WhatsApp.
 */
export function ReminderList() {
  const [data, setData] = useState<ReminderListData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    unwrap(api.GET("/api/v1/platform/reminders")).then(
      (result) => alive && (setData(result), setError(null)),
      (caught: unknown) => alive && setError(errorMessage(caught)),
    );
    return () => {
      alive = false;
    };
  }, []);

  return (
    <section aria-labelledby="titre-relances" className="space-y-5">
      <PageHeader
        id="titre-relances"
        title="À relancer"
        description="Boutiques dont l'essai ou l'abonnement se termine (de la veille à J+3), et celles mises en pause depuis moins de 7 jours. La tâche de nuit a déjà prévenu par la cloche et l'e-mail ; ici, on écrit à ceux qui n'en ont pas."
      />
      {error && <Notice tone="danger">{error}</Notice>}
      {!data && !error && <Skeleton label="Chargement des boutiques à relancer" />}
      {data && (
        <>
          <p className="text-encre-douce" aria-live="polite">
            {data.items.length} boutique{data.items.length > 1 ? "s" : ""} · mis à jour le{" "}
            {formatDateTime(data.computed_at)}
          </p>
          {data.items.length === 0 ? (
            <EmptyState title="Personne à relancer aujourd'hui.">
              Aucun essai ni abonnement ne se termine ces jours-ci.
            </EmptyState>
          ) : (
            <ul aria-label="Boutiques à relancer" className="space-y-3">
              {data.items.map((item) => (
                <li key={item.company_id}>
                  <ReminderCard item={item} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

function ReminderCard({ item }: { item: ReminderItem }) {
  const [message, setMessage] = useState(item.message);
  const stage = STAGES[item.stage];
  const fieldId = `message-${item.company_id}`;
  const reachable = item.contacts.filter((contact) => phoneDigits(contact.phone));
  return (
    <Card aria-labelledby={`relance-${item.company_id}`} className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id={`relance-${item.company_id}`} className="font-bold">
            <Link href={`/companies/${item.company_id}`} className="underline">
              {item.name}
            </Link>
          </h2>
          <p className="text-sm text-encre-douce">
            {kindLabel(item)} · fin le {formatDate(item.ends_at)} · pause{" "}
            {item.stage === "suspended" ? "depuis" : "prévue"} le {formatDate(item.pause_on)}
          </p>
          <p className="text-sm text-encre-douce">{sentLabel(item)}</p>
        </div>
        <Pill tone={stage.tone}>{stage.label}</Pill>
      </div>
      <div>
        <label htmlFor={fieldId} className={LABEL}>
          Message WhatsApp (modifiable)
        </label>
        <textarea
          id={fieldId}
          rows={3}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          className={`${FIELD} mt-1 min-h-24 py-2`}
        />
      </div>
      {reachable.length === 0 ? (
        <p className="text-sm text-encre-douce">Aucun gérant avec un numéro de téléphone.</p>
      ) : (
        <ul className="flex flex-col gap-2" aria-label={`Gérants de ${item.name}`}>
          {reachable.map((contact) => (
            <li
              key={`${contact.full_name}-${contact.phone}`}
              className="flex flex-wrap items-center gap-2"
            >
              <span className="min-w-40 font-semibold">{contact.full_name}</span>
              <a
                href={whatsappLink(contact.phone, message)}
                target="_blank"
                rel="noopener noreferrer"
                className={`${BUTTON.primary} inline-flex items-center gap-2`}
              >
                <MessageCircle aria-hidden="true" className="size-4" />
                Écrire sur WhatsApp
                <span className="sr-only"> à {contact.full_name}</span>
              </a>
              <a
                href={`tel:+${phoneDigits(contact.phone)}`}
                className={`${BUTTON.secondary} inline-flex items-center gap-2`}
              >
                <Phone aria-hidden="true" className="size-4" />
                Appeler
                <span className="sr-only"> {contact.full_name}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
