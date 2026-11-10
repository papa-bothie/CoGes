import { PackagePlus, ShoppingCart, UserPlus, type LucideIcon } from "lucide-react";
import Link from "next/link";

import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

const t = labels.firstSteps;

export type FirstStep = {
  key: string;
  href: string;
  label: string;
  hint: string;
  icon: LucideIcon;
};

/** Les trois premiers gestes, dans l'ordre où ils servent (ADR 0118). */
export const FIRST_STEPS: FirstStep[] = [
  {
    key: "product",
    href: "/products/new",
    label: t.product,
    hint: t.productHint,
    icon: PackagePlus,
  },
  {
    key: "customer",
    href: "/customers/new",
    label: t.customer,
    hint: t.customerHint,
    icon: UserPlus,
  },
  { key: "sale", href: "/sales/new", label: t.sale, hint: t.saleHint, icon: ShoppingCart },
];

/**
 * Tableau de bord d'une boutique neuve : aucun article, aucune vente. Chaque geste n'est
 * montré qu'à qui peut ouvrir son écran (`visible`, au droit exact du registre).
 */
export function FirstSteps({ visible }: { visible: (href: string) => boolean }) {
  const steps = FIRST_STEPS.filter((step) => visible(step.href));
  if (steps.length === 0) return null;
  return (
    <section
      aria-labelledby="premiers-pas"
      className="rounded-carte border-2 border-ventes bg-ventes-teinte p-carte"
    >
      <h2 id="premiers-pas" className="text-[22px] font-extrabold">
        {t.title}
      </h2>
      <p className="mt-1 text-lg text-encre-2">{t.intro}</p>
      <ol className="mt-4 grid gap-3 md:grid-cols-3">
        {steps.map((step, index) => (
          <li key={step.key}>
            <Link
              href={step.href}
              className={cn(
                "flex h-full min-h-cible items-start gap-3 rounded-tuile border border-border bg-card p-4",
                "outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50",
              )}
            >
              <span
                aria-hidden
                className="grid size-10 shrink-0 place-items-center rounded-full bg-ventes text-lg font-extrabold text-primary-foreground"
              >
                {index + 1}
              </span>
              <span className="space-y-1">
                <span className="flex items-center gap-2 text-libelle">
                  <step.icon className="size-5" aria-hidden />
                  {step.label}
                </span>
                <span className="block text-encre-2">{step.hint}</span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
