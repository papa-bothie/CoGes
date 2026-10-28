import type { Schemas } from "@/lib/api/schema";

/** Tous les moyens de paiement de l'API, pour relire un brouillon (ADR 0101). */
export const PAYMENT_METHODS: readonly Schemas["PaymentMethod"][] = [
  "cash",
  "mobile_money",
  "wave",
  "orange_money",
  "bank_transfer",
  "card",
  "cheque",
];
