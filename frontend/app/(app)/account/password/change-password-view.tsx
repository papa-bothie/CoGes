"use client";

import { useState } from "react";

import { PasswordChangeForm } from "@/components/password-change-form";
import { labels } from "@/lib/labels";

const t = labels.accountPassword;

/**
 * « Changer mon mot de passe » (prompt 28, C2, ADR 0098) : ouvert à tous les rôles depuis
 * le menu du compte, sans aucun droit (le vendeur et le comptable n'ont pas Réglages). Le
 * serveur ferme les autres sessions et renouvelle celle de ce navigateur.
 */
export function ChangePasswordView() {
  const [done, setDone] = useState(false);
  // Un formulaire neuf après chaque changement : les champs repartent vides.
  const [round, setRound] = useState(0);
  return (
    <div className="mx-auto flex max-w-[480px] flex-col gap-5">
      <div>
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title}</h1>
        <p className="text-lg text-muted-foreground">{t.intro}</p>
      </div>
      {done && (
        <p
          role="status"
          className="rounded-champ bg-ventes-teinte px-4 py-3.5 font-bold text-ventes-encre"
        >
          {t.done}
        </p>
      )}
      <section className="rounded-carte border border-border bg-card p-carte">
        <PasswordChangeForm
          key={round}
          currentLabel={t.current}
          submitLabel={t.submit}
          onDone={() => {
            setDone(true);
            setRound((count) => count + 1);
          }}
        />
      </section>
    </div>
  );
}
