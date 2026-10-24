import type { Metadata } from "next";
import { Suspense } from "react";

import { CompanyList } from "./company-list";

export const metadata: Metadata = { title: "Entreprises" };

export default function CompaniesPage() {
  return (
    <Suspense>
      <CompanyList />
    </Suspense>
  );
}
