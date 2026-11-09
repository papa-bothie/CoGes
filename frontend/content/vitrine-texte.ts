/**
 * Textes de la page d'accueil publique (prompt 37, ADR 0115). Chaque phrase décrit ce que
 * CoGes fait déjà : rien sur le hors ligne au-delà du brouillon retrouvé (ADR 0101), aucun prix
 * tant qu'ils ne sont pas arrêtés, l'essai à sa durée réelle (ADR 0091). `vitrine-texte.test.ts`
 * refuse les promesses interdites.
 */
import { vitrine } from "./vitrine";

/** Durée de l'essai, fixée en base par l'ADR 0091 (trigger `companies_start_trial`). */
export const TRIAL_DAYS = 30;

export type Rubrique = "ventes" | "stock" | "argent" | "clients" | "conseils" | "depenses";
export type IconName =
  | "shopping-cart"
  | "package"
  | "wallet"
  | "layout-dashboard"
  | "scan-barcode"
  | "users"
  | "hand-coins"
  | "boxes"
  | "trending-up"
  | "user-check"
  | "smile"
  | "smartphone"
  | "download";

export const texte = {
  meta: {
    title: "CoGes — les ventes, le stock et l'argent de votre boutique",
    description:
      "CoGes aide les commerçants à suivre leurs ventes, leur stock, leur caisse et leurs dettes, en francs CFA, sur téléphone ou ordinateur.",
    shareAlt: "CoGes, votre boutique simplement : l'écran de vente sur ordinateur.",
  },
  nav: {
    features: "Fonctionnalités",
    questions: "Questions",
    login: "Se connecter",
    whatsapp: "WhatsApp",
    menu: "Menu",
    closeMenu: "Fermer le menu",
    home: "CoGes, accueil",
  },
  hero: {
    title: "Les ventes, le stock et l'argent de votre boutique, au même endroit.",
    lead: "Vous vendez, CoGes compte : ce qui est vendu, ce qui reste en rayon, ce qui est dans la caisse et qui vous doit quoi. En francs CFA, sur téléphone ou ordinateur.",
    whatsapp: "Écrire sur WhatsApp",
    howItWorks: "Voir comment ça marche",
    trial: `Chaque nouvelle boutique commence par ${TRIAL_DAYS} jours d'essai gratuit.`,
    illustrationAlt: "",
  },
  problems: {
    title: "Les questions de tous les jours, réglées",
    items: [
      {
        question: "Qui me doit quoi ?",
        answer:
          "Une vente à crédit devient une dette au nom du client. Vous voyez qui doit combien, et vous encaissez en un geste.",
        icon: "hand-coins",
        rubrique: "clients",
      },
      {
        question: "Qu'est-ce qui reste en rayon ?",
        answer:
          "Le stock baisse à chaque vente et monte à chaque livraison. CoGes vous signale les articles bientôt épuisés.",
        icon: "boxes",
        rubrique: "stock",
      },
      {
        question: "Combien j'ai vendu aujourd'hui ?",
        answer:
          "Vendu aujourd'hui, argent dans la caisse, gagné ou perdu sur le mois : les chiffres sont là dès l'ouverture.",
        icon: "trending-up",
        rubrique: "ventes",
      },
      {
        question: "Mon vendeur a-t-il tout encaissé ?",
        answer:
          "Chaque vente garde le nom de la personne qui l'a faite, et les entrées et sorties du jour se lisent ligne par ligne.",
        icon: "user-check",
        rubrique: "argent",
      },
    ],
  },
  features: {
    title: "Ce que fait CoGes",
    lead: "Six outils simples, pensés pour une boutique.",
    items: [
      {
        title: "Ventes et caisse",
        body: "Touchez les articles, choisissez espèces, Wave, Orange Money ou crédit. Le reçu est prêt à imprimer ou à envoyer sur WhatsApp.",
        icon: "shopping-cart",
        rubrique: "ventes",
      },
      {
        title: "Stock",
        body: "Livraisons, corrections et pertes enregistrées : le stock suit chaque vente, et un article épuisé ne se vend pas par erreur.",
        icon: "package",
        rubrique: "stock",
      },
      {
        title: "Argent et dettes",
        body: "Entrées, sorties, dépenses, dettes des clients et des fournisseurs : tout est compté en francs CFA, sans tableur.",
        icon: "wallet",
        rubrique: "argent",
      },
      {
        title: "Tableau de bord",
        body: "Ce que vous avez vendu, ce qui est dans la caisse, ce qu'on vous doit et ce qui manque, sur un seul écran.",
        icon: "layout-dashboard",
        rubrique: "conseils",
      },
      {
        title: "Scan des codes-barres",
        body: "Recevez une livraison en scannant les codes-barres avec la caméra du téléphone. À la caisse, une douchette suffit.",
        icon: "scan-barcode",
        rubrique: "depenses",
      },
      {
        title: "Gérant, vendeur, comptable",
        body: "Chacun a son propre mot de passe, et c'est le gérant qui choisit ce que chacun peut voir et faire.",
        icon: "users",
        rubrique: "clients",
      },
    ],
  },
  preview: {
    title: "À quoi ça ressemble",
    lead: "De vrais écrans de CoGes, sur une boutique de démonstration.",
    phoneAlt:
      "CoGes sur téléphone : l'accueil d'une épicerie de démonstration, avec le bouton « Nouvelle vente », le montant vendu aujourd'hui, l'argent dans la caisse, ce que les clients doivent, les articles à surveiller et les dernières ventes.",
    desktopAlt:
      "CoGes sur ordinateur : l'écran « Nouvelle vente » d'une épicerie de démonstration, avec la recherche par nom ou code-barres, les rayons, les articles et leur prix, et à droite le panier, le total et le choix du paiement (espèces, Wave, Orange Money).",
    phoneCaption: "Sur téléphone : l'accueil",
    desktopCaption: "Sur ordinateur : la caisse",
  },
  benefits: {
    title: "Fait pour votre boutique",
    items: [
      {
        title: "Simple",
        body: "Des mots de tous les jours et de grands boutons, sans jargon comptable.",
        icon: "smile",
      },
      {
        title: "Sur votre téléphone",
        body: "CoGes est pensé d'abord pour le téléphone. Il marche aussi sur ordinateur et tablette.",
        icon: "smartphone",
      },
      {
        title: "Sur l'écran d'accueil",
        body: "Ajoutez CoGes à l'écran d'accueil du téléphone et ouvrez-le comme une application, sans passer par un magasin d'applications.",
        icon: "download",
      },
    ],
    illustrationAlt: "",
  },
  faq: {
    title: "Questions fréquentes",
    items: [
      {
        question: "Combien coûte CoGes ?",
        answer: `Les prix ne sont pas encore publiés ici : écrivez-nous sur WhatsApp, nous vous répondons avec l'offre qui convient à votre boutique. Chaque nouvelle boutique commence par ${TRIAL_DAYS} jours d'essai gratuit.`,
      },
      {
        question: "Faut-il un ordinateur ?",
        answer:
          "Non. Un téléphone avec internet suffit. Si vous avez un ordinateur ou une tablette, CoGes y marche aussi, avec le même compte.",
      },
      {
        question: "Et si la connexion internet coupe ?",
        answer:
          "CoGes a besoin d'internet pour enregistrer une vente. Si la connexion coupe pendant une saisie, ce que vous aviez commencé est gardé sur le téléphone et vous le retrouvez au retour.",
      },
      {
        question: "Mes vendeurs peuvent-ils l'utiliser ?",
        answer:
          "Oui. Chaque personne a son propre accès : gérant, vendeur ou comptable. Le gérant choisit ce que chacun peut faire. Le nombre de personnes dépend de votre offre.",
      },
      {
        question: "Qui voit mes chiffres ?",
        answer:
          "Chaque personne se connecte avec son propre mot de passe et ne voit que ce que le gérant lui permet. Pour toute question sur vos données, écrivez-nous.",
      },
      {
        question: "Comment commencer ?",
        answer: `Écrivez-nous sur WhatsApp (${vitrine.supportHours.charAt(0).toLowerCase()}${vitrine.supportHours.slice(1)}). Nous créons votre boutique avec vous et vous montrons les premiers pas.`,
      },
    ],
  },
  footer: {
    tagline: "Les ventes, le stock et l'argent de votre boutique.",
    contact: "Nous écrire sur WhatsApp",
    hours: vitrine.supportHours,
    login: "Se connecter",
    copyright: `© ${new Date().getFullYear()} CoGes`,
  },
} as const;
