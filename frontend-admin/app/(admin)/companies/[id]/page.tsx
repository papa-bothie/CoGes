import { CompanyDetailView } from "./company-detail";

/**
 * Adresse de l'application commerçante, lue **à l'exécution** (une même image sert la
 * préproduction et la production) : l'accès support y ouvre la boutique (ADR 0092).
 */
function merchantUrl(): string {
  return process.env.COGES_MERCHANT_URL || "http://localhost:3000";
}

export default async function CompanyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CompanyDetailView companyId={id} merchantUrl={merchantUrl()} />;
}
