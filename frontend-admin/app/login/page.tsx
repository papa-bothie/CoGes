import type { Metadata } from "next";
import { Suspense } from "react";

import { ThemeToggle } from "@/components/theme-toggle";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Connexion" };

export default function LoginPage() {
  return (
    <main className="flex min-h-screen flex-col">
      <div className="flex items-center bg-admin px-4 py-0.5 text-admin-encre">
        <span className="font-bold">CoGes</span>{" "}
        <span className="ml-2 rounded-md border border-admin-trait px-2 py-0.5 text-sm font-semibold tracking-wide uppercase">
          Administration
        </span>
        <ThemeToggle className="ml-auto hover:bg-admin-trait" />
      </div>
      <div className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-sm rounded-2xl border border-trait bg-surface p-6">
          <p className="text-sm font-semibold tracking-wide text-encre-douce uppercase">CoGes</p>
          <h1 className="mt-1 mb-6 text-2xl font-bold">Administration</h1>
          <Suspense>
            <LoginForm />
          </Suspense>
          <p className="mt-6 text-sm text-encre-douce">
            Réservé à l&apos;équipe CoGes. Les commerçants se connectent sur l&apos;application
            habituelle.
          </p>
        </div>
      </div>
    </main>
  );
}
