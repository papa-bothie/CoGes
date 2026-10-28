import type { Metadata } from "next";

import { ThemeToggle } from "@/components/theme-toggle";

import { AcceptInvitation } from "./accept-invitation";

export const metadata: Metadata = { title: "Rejoindre l'équipe" };

export default async function InvitationPage({ params }: PageProps<"/invitation/[token]">) {
  const { token } = await params;
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
          <h1 className="mb-2 text-2xl font-bold">Rejoindre l&apos;équipe</h1>
          <p className="mb-6 text-encre-douce">
            Choisissez votre mot de passe pour activer votre compte d&apos;administration.
          </p>
          <AcceptInvitation token={token} />
        </div>
      </div>
    </main>
  );
}
