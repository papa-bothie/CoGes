import type { Metadata } from "next";
import { Suspense } from "react";

import { UserDirectory } from "./user-directory";

export const metadata: Metadata = { title: "Utilisateurs" };

export default function UsersPage() {
  return (
    <Suspense>
      <UserDirectory />
    </Suspense>
  );
}
