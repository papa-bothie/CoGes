"use client";

import { Menu, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { texte } from "@/content/vitrine-texte";

import { WhatsAppLink } from "./links";

const t = texte.nav;

/**
 * Menu du téléphone, seul JavaScript de la vitrine (prompt 37) : « Fonctionnalités »,
 * « Questions » et WhatsApp. « Se connecter » reste hors du menu, toujours visible.
 * Échap ou un lien choisi le referment ; le focus revient au bouton.
 */
export function MobileMenu() {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const close = () => setOpen(false);

  return (
    <div className="md:hidden">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={panel}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex size-cible items-center justify-center rounded-bouton border-2 border-input bg-card text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/60"
      >
        {open ? <X aria-hidden className="size-6" /> : <Menu aria-hidden className="size-6" />}
        <span className="sr-only">{open ? t.closeMenu : t.menu}</span>
      </button>
      <nav
        id={panel}
        aria-label={t.menu}
        hidden={!open}
        className="absolute inset-x-0 top-full border-b border-border bg-background px-4 pt-2 pb-5 shadow-lg motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-top-2"
      >
        <ul className="space-y-1">
          <li>
            <a
              href="#fonctionnalites"
              onClick={close}
              className="flex min-h-cible items-center rounded-mini px-3 text-libelle hover:bg-voile"
            >
              {t.features}
            </a>
          </li>
          <li>
            <a
              href="#questions"
              onClick={close}
              className="flex min-h-cible items-center rounded-mini px-3 text-libelle hover:bg-voile"
            >
              {t.questions}
            </a>
          </li>
        </ul>
        <WhatsAppLink variant="borde" className="mt-3 w-full">
          {t.whatsapp}
        </WhatsAppLink>
      </nav>
    </div>
  );
}
