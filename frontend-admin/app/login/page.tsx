import { Suspense } from "react";

import { LoginForm } from "./login-form";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm rounded-lg border border-trait bg-surface p-6 shadow-sm">
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
    </main>
  );
}
