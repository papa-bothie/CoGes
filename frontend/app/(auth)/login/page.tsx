import { Store } from "lucide-react";
import type { Metadata } from "next";
import { Suspense } from "react";

import { Card } from "@/components/ui/card";
import { labels } from "@/lib/labels";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: labels.login.title };

export default function LoginPage() {
  return (
    <main className="grid min-h-dvh place-items-center p-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex items-center justify-center gap-2.5">
          <div className="grid size-10 place-items-center rounded-lg bg-primary text-primary-foreground">
            <Store className="size-5" aria-hidden />
          </div>
          <div>
            <p className="text-xl leading-tight font-bold">{labels.app.name}</p>
            <p className="text-xs text-muted-foreground">{labels.app.tagline}</p>
          </div>
        </div>
        <Card className="gap-5 px-6 py-6">
          <div>
            <h1 className="text-xl font-bold">{labels.login.title}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{labels.login.subtitle}</p>
          </div>
          <Suspense>
            <LoginForm />
          </Suspense>
        </Card>
      </div>
    </main>
  );
}
