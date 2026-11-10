import type { Metadata } from "next";
import { Suspense } from "react";

import { RequestList } from "./request-list";

export const metadata: Metadata = { title: "Demandes" };

export default function SignupRequestsPage() {
  return (
    <Suspense>
      <RequestList />
    </Suspense>
  );
}
