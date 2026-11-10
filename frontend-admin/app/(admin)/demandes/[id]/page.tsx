import type { Metadata } from "next";

import { RequestDetail } from "./request-detail";

export const metadata: Metadata = { title: "Demande d'inscription" };

/** Adresse de la boutique, lue à l'exécution : le lien d'accès envoyé sur WhatsApp. */
function merchantUrl(): string {
  return process.env.COGES_MERCHANT_URL || "http://localhost:3000";
}

export default async function SignupRequestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RequestDetail requestId={id} merchantUrl={merchantUrl()} />;
}
