import { CompanyDetailView } from "./company-detail";

export default async function CompanyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CompanyDetailView companyId={id} />;
}
