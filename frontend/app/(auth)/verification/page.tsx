import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { BrandLogo } from "@/components/brand/brand";
import { labels } from "@/lib/labels";
import { signupConfig } from "@/lib/signup/config";

import { VerifyLink } from "./verify-link";

export const metadata: Metadata = { title: labels.signup.invalidTitle };

/** Adresse sans jeton : celle qui reste après lecture du lien, ou rechargée. */
export default async function VerificationWithoutToken() {
  const config = await signupConfig();
  if (!config.enabled) notFound();
  return (
    <main className="flex min-h-dvh justify-center bg-background px-4 py-10">
      <div className="w-full max-w-[480px] space-y-6">
        <BrandLogo className="h-auto w-[200px]" />
        <VerifyLink token={null} />
      </div>
    </main>
  );
}
