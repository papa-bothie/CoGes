/**
 * Une couleur par rubrique (maquette v2, `tokens.css`). Tailwind ne voit que des classes
 * écrites en entier : chaque combinaison est donc listée ici, jamais composée à la volée.
 */
export type Rubrique = "ventes" | "stock" | "argent" | "clients" | "depenses" | "conseils";

export const RUBRIQUES: readonly Rubrique[] = [
  "ventes",
  "stock",
  "argent",
  "clients",
  "depenses",
  "conseils",
];

type Classes = {
  /** Fond plein et texte blanc (bouton, puce choisie « pleine », disque d'icône). */
  solid: string;
  /** Fond teinté (tuile, encart). */
  tint: string;
  /** Texte foncé sur teinte. */
  ink: string;
  /** Teinte + encre + bordure pleine : élément choisi « léger ». */
  picked: string;
  /** Bordure et anneau de focus d'un champ de la rubrique. */
  focus: string;
  /** Fond de la touche pressée sur le pavé numérique. */
  pressed: string;
};

export const RUBRIQUE_CLASSES: Record<Rubrique, Classes> = {
  ventes: {
    solid: "bg-ventes text-primary-foreground",
    tint: "bg-ventes-teinte",
    ink: "text-ventes-encre",
    picked: "border-ventes bg-ventes-teinte text-ventes-encre",
    focus: "focus-visible:border-ventes focus-visible:outline-ventes-anneau",
    pressed: "active:bg-ventes-teinte",
  },
  stock: {
    solid: "bg-stock text-primary-foreground",
    tint: "bg-stock-teinte",
    ink: "text-stock-encre",
    picked: "border-stock bg-stock-teinte text-stock-encre",
    focus: "focus-visible:border-stock focus-visible:outline-stock-anneau",
    pressed: "active:bg-stock-teinte",
  },
  argent: {
    solid: "bg-argent text-primary-foreground",
    tint: "bg-argent-teinte",
    ink: "text-argent-encre",
    picked: "border-argent bg-argent-teinte text-argent-encre",
    focus: "focus-visible:border-argent focus-visible:outline-argent-anneau",
    pressed: "active:bg-argent-teinte",
  },
  clients: {
    solid: "bg-clients text-primary-foreground",
    tint: "bg-clients-teinte",
    ink: "text-clients-encre",
    picked: "border-clients bg-clients-teinte text-clients-encre",
    focus: "focus-visible:border-clients focus-visible:outline-clients-anneau",
    pressed: "active:bg-clients-teinte",
  },
  depenses: {
    solid: "bg-depenses text-primary-foreground",
    tint: "bg-depenses-teinte",
    ink: "text-depenses-encre",
    picked: "border-depenses bg-depenses-teinte text-depenses-encre",
    focus: "focus-visible:border-depenses focus-visible:outline-depenses-anneau",
    pressed: "active:bg-depenses-teinte",
  },
  conseils: {
    solid: "bg-conseils text-primary-foreground",
    tint: "bg-conseils-teinte",
    ink: "text-conseils-encre",
    picked: "border-conseils bg-conseils-teinte text-conseils-encre",
    focus: "focus-visible:border-conseils focus-visible:outline-conseils-anneau",
    pressed: "active:bg-conseils-teinte",
  },
};

/** Bordure pleine de la rubrique, pour la puce ou le grand choix « plein ». */
export const RUBRIQUE_BORDER: Record<Rubrique, string> = {
  ventes: "border-ventes",
  stock: "border-stock",
  argent: "border-argent",
  clients: "border-clients",
  depenses: "border-depenses",
  conseils: "border-conseils",
};

/** Champ de saisie de la maquette : bordure 2 px, anneau de 3 px à la couleur de la rubrique. */
export function fieldClasses(rubrique: Rubrique): string {
  return [
    "w-full rounded-champ border-2 border-input bg-card text-foreground",
    "outline-none focus-visible:outline-3 focus-visible:outline-solid",
    "disabled:cursor-not-allowed disabled:opacity-50",
    "aria-invalid:border-destructive",
    RUBRIQUE_CLASSES[rubrique].focus,
  ].join(" ");
}
