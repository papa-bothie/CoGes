"use client";

import {
  AlertTriangle,
  Banknote,
  Bell,
  Box,
  CreditCard,
  Droplets,
  Gift,
  HandCoins,
  Home,
  Lightbulb,
  PackageX,
  Plus,
  ShoppingCart,
  Users,
  Wallet,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import { AmountField, AmountShortcuts, NumericPad } from "@/components/kit/amount-field";
import { BottomNav, TopBar, type BarItem } from "@/components/kit/app-bars";
import { Chip } from "@/components/kit/chip";
import { ChoiceGroup } from "@/components/kit/choice-group";
import { ChoiceTiles } from "@/components/kit/choice-tile";
import { DayBars } from "@/components/kit/day-bars";
import { Banner, FieldHint, SuccessScreen } from "@/components/kit/feedback";
import { KitCard } from "@/components/kit/kit-card";
import { Avatar, ListRow, ProductSquare } from "@/components/kit/list-row";
import { QuantityStepper } from "@/components/kit/quantity-stepper";
import { RUBRIQUES } from "@/components/kit/rubrique";
import { StatTile } from "@/components/kit/stat-tile";
import { StatusPill } from "@/components/kit/status-pill";
import { ThemeToggle } from "@/components/shell/theme-toggle";
import { ToggleSwitch } from "@/components/kit/toggle-switch";
import { Button } from "@/components/ui/button";
import { formatAmount } from "@/lib/format";
import { labels } from "@/lib/labels";

/*
 * Données d'exemple de la maquette (Alimentation Keur Fatou, mardi 6 octobre 2026) : les
 * textes viennent des sources de docs/design/maquette-v2/source/.
 */
const NAV: BarItem[] = [
  { href: "#accueil", label: labels.kit.nav.home, icon: Home, rubrique: "ventes", active: true },
  {
    href: "#vendre",
    label: labels.kit.nav.sell,
    icon: ShoppingCart,
    rubrique: "ventes",
    active: false,
  },
  { href: "#stock", label: labels.kit.nav.stock, icon: Box, rubrique: "stock", active: false },
  {
    href: "#clients",
    label: labels.kit.nav.clients,
    icon: Users,
    rubrique: "clients",
    active: false,
  },
  {
    href: "#argent",
    label: labels.kit.nav.money,
    icon: CreditCard,
    rubrique: "argent",
    active: false,
  },
  {
    href: "#conseils",
    label: labels.kit.nav.advice,
    icon: Lightbulb,
    rubrique: "conseils",
    active: false,
  },
];

const WEEK = [
  { label: "Mer", display: "62 000", weight: 62000 },
  { label: "Jeu", display: "71 500", weight: 71500 },
  { label: "Ven", display: "98 000", weight: 98000 },
  { label: "Sam", display: "124 000", weight: 124000 },
  { label: "Dim", display: "45 000", weight: 45000 },
  { label: "Lun", display: "80 500", weight: 80500 },
  { label: labels.kit.chartToday, display: "87 500", weight: 87500, current: true },
];

const ARTICLES = [
  "Riz brisé 25 kg",
  "Huile Dinor 1 L",
  "Sucre en morceaux 1 kg",
  "Lait Vitalait 400 g",
  "Café Touba 250 g",
  "Savon Madar",
  "Oignons 1 kg",
  "Thé Lipton 25 sachets",
  "Pâtes 500 g",
  "Tomate concentrée 400 g",
  "Eau Kirène 1,5 L",
  "Bougies (paquet)",
];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-4">
      <h2 className="text-titre-carte">{title}</h2>
      {children}
    </section>
  );
}

export function Showcase() {
  const [payment, setPayment] = useState<"all" | "part" | "credit">("part");
  const [method, setMethod] = useState("Espèces");
  const [category, setCategory] = useState("Tout");
  const [amount, setAmount] = useState("7500");
  const [qty, setQty] = useState("2");
  const [reason, setReason] = useState<"broken" | "gift" | "spoiled" | "lost">("broken");
  const [switchOn, setSwitchOn] = useState(true);

  return (
    <div className="min-h-dvh bg-background pb-24 md:pb-0">
      <TopBar
        companyName="Alimentation Keur Fatou"
        items={NAV}
        trailing={
          <>
            <Button variant="ghost" size="icon-lg" aria-label={labels.kit.nav.unread(3)}>
              <Bell aria-hidden />
            </Button>
            <ThemeToggle />
          </>
        }
      />
      <main className="mx-auto max-w-page space-y-10 px-4 py-6 md:px-marge-page">
        <div>
          <h1 className="text-titre-page">{labels.kit.showcase.title}</h1>
          <p className="text-muted-foreground">{labels.kit.showcase.subtitle}</p>
        </div>

        <Section title="Boutons">
          <div className="flex flex-wrap items-center gap-3">
            <Button size="principal">
              <Plus aria-hidden /> Nouvelle vente
            </Button>
            <Button size="standard">Enregistrer</Button>
            <Button size="standard" variant="secondaire">
              Annuler
            </Button>
            <Button size="principal" disabled>
              Encaisser 7 500 F
            </Button>
          </div>
          <div className="flex flex-wrap gap-3">
            {RUBRIQUES.map((rubrique) => (
              <Button key={rubrique} size="standard" variant={rubrique}>
                {rubrique}
              </Button>
            ))}
          </div>
        </Section>

        <Section title="Tuiles chiffrées">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile
              rubrique="ventes"
              icon={ShoppingCart}
              label="Vendu aujourd'hui"
              value={formatAmount("87500")}
              detail="14 ventes"
            />
            <StatTile
              rubrique="argent"
              icon={Wallet}
              label="Dans la caisse"
              value={formatAmount("152000")}
              detail="Espèces et mobile money"
            />
            <StatTile
              rubrique="clients"
              icon={Users}
              label="Les clients vous doivent"
              value={formatAmount("54500")}
              detail="5 clients · Encaisser"
            />
            <StatTile
              rubrique="stock"
              icon={AlertTriangle}
              label="Stock à surveiller"
              value="3 articles"
              detail="Bientôt épuisés"
            />
          </div>
          <div className="grid max-w-sm grid-cols-2 gap-3">
            <StatTile
              compact
              rubrique="ventes"
              label="Vendu aujourd'hui"
              value={formatAmount("87500")}
            />
            <StatTile
              compact
              rubrique="argent"
              label="Dans la caisse"
              value={formatAmount("152000")}
            />
          </div>
        </Section>

        <Section title="Carte, liste et pastilles">
          <KitCard
            title="Dernières ventes"
            action={
              <a className="font-semibold text-primary underline" href="#ventes">
                Tout voir
              </a>
            }
          >
            <ListRow
              leading={<Avatar name="Awa Diop" rubrique="ventes" />}
              title="Awa Diop"
              subtitle="10 h 42"
              trailing={
                <>
                  <span className="text-libelle font-extrabold numeric">
                    {formatAmount("12500")}
                  </span>
                  <StatusPill status="paid" className="min-w-[150px]" />
                </>
              }
            />
            <ListRow
              leading={<Avatar name={null} />}
              title={labels.kit.walkIn}
              subtitle="10 h 15"
              trailing={
                <>
                  <span className="text-libelle font-extrabold numeric">
                    {formatAmount("3200")}
                  </span>
                  <StatusPill status="paid" className="min-w-[150px]" />
                </>
              }
            />
            <ListRow
              leading={<Avatar name="Moussa Fall" rubrique="clients" />}
              title="Moussa Fall"
              subtitle="9 h 58"
              trailing={
                <>
                  <span className="text-libelle font-extrabold numeric">
                    {formatAmount("25000")}
                  </span>
                  <StatusPill
                    status="remaining"
                    amount={formatAmount("10000")}
                    className="min-w-[150px]"
                  />
                </>
              }
            />
          </KitCard>
          <div className="flex flex-wrap gap-2">
            <StatusPill status="paid" />
            <StatusPill status="remaining" amount={formatAmount("10000")} />
            <StatusPill status="returned" amount={formatAmount("5000")} />
            <StatusPill status="cancelled" />
            <StatusPill status="writtenOff" />
          </div>
          <div className="flex flex-wrap gap-3">
            {ARTICLES.map((name, index) => (
              <ProductSquare key={name} name={name} tone={index + 1} />
            ))}
          </div>
        </Section>

        <Section title="Puces et grand choix">
          <div className="flex flex-wrap gap-2.5">
            {["Tout", "Céréales", "Huiles", "Boissons", "Hygiène", "Épicerie"].map((name) => (
              <Chip key={name} selected={category === name} onClick={() => setCategory(name)}>
                {name}
              </Chip>
            ))}
          </div>
          <div className="flex flex-wrap gap-2.5">
            {["Espèces", "Wave", "Orange Money"].map((name) => (
              <Chip
                key={name}
                selected={method === name}
                rubrique="argent"
                tone="plein"
                onClick={() => setMethod(name)}
              >
                {name}
              </Chip>
            ))}
          </div>
          <ChoiceGroup
            label="Le client paie"
            value={payment}
            onValueChange={setPayment}
            choices={[
              { value: "all", label: "Tout payé" },
              { value: "part", label: "Une partie" },
              { value: "credit", label: "À crédit" },
            ]}
          />
        </Section>

        <Section title="Montant, pavé numérique, quantité">
          <div className="grid max-w-md gap-4">
            <AmountField label="Il donne maintenant" value={amount} onChange={setAmount} />
            <AmountShortcuts
              shortcuts={[
                { label: "La moitié : 10 500 F", value: "10500" },
                { label: "5 500 F", value: "5500" },
              ]}
              onPick={setAmount}
            />
            <NumericPad value={amount} onChange={setAmount} />
            <Banner>Il restera 13 500 F à payer</Banner>
            <QuantityStepper value={qty} onChange={setQty} itemName="Huile Dinor 1 L" />
            <FieldHint>Tout nombre se tape librement.</FieldHint>
          </div>
        </Section>

        <Section title="Tuiles de choix">
          <ChoiceTiles
            label="Pourquoi ?"
            value={reason}
            onValueChange={setReason}
            choices={[
              { value: "broken", label: "Cassé", icon: PackageX },
              { value: "spoiled", label: "Abîmé ou périmé", icon: Droplets },
              { value: "gift", label: "Offert", icon: Gift },
              { value: "lost", label: "Perdu", icon: HandCoins },
            ]}
          />
        </Section>

        <Section title="Graphique et interrupteur">
          <KitCard title="Vos ventes des 7 derniers jours">
            <DayBars label="Ventes des 7 derniers jours" bars={WEEK} />
          </KitCard>
          <div className="max-w-lg">
            <ToggleSwitch
              label="Imprimer le reçu après chaque vente"
              checked={switchOn}
              onCheckedChange={setSwitchOn}
            />
          </div>
        </Section>

        <Section title="Écran de succès">
          <KitCard>
            <SuccessScreen
              title="Vente enregistrée"
              detail="Awa Diop a payé 12 500 F"
              actions={
                <>
                  <Button size="principal">
                    <Banknote aria-hidden /> Nouvelle vente
                  </Button>
                  <Button size="standard" variant="secondaire">
                    Imprimer le reçu
                  </Button>
                </>
              }
            />
          </KitCard>
        </Section>
      </main>
      <BottomNav items={NAV.slice(0, 5)} />
    </div>
  );
}
