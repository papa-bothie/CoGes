import type { Metadata } from "next";

import { BrandLogo } from "@/components/brand/brand";
import { labels } from "@/lib/labels";

import { FirstPasswordForm } from "./first-password-form";

export const metadata: Metadata = { title: labels.login.firstPassword.title };

/** « Choisissez votre mot de passe » : après un mot de passe provisoire (ADR 0074). */
export default function FirstPasswordPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-[440px] space-y-6">
        <BrandLogo className="h-auto w-[220px]" />
        <h1 className="text-[32px] leading-tight font-extrabold">
          {labels.login.firstPassword.title}
        </h1>
        <p className="text-lg text-encre-2">{labels.login.firstPassword.intro}</p>
        <FirstPasswordForm />
      </div>
    </main>
  );
}
