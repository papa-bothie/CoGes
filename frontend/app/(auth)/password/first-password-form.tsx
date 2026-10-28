"use client";

import { PasswordChangeForm } from "@/components/password-change-form";
import { logout } from "@/lib/auth/session";
import { labels } from "@/lib/labels";

const t = labels.login.firstPassword;

/**
 * Le mot de passe reçu, puis le nouveau deux fois. Le serveur revérifie tout (longueur,
 * mot de passe actuel, différent de l'ancien) et lève l'obligation (`POST /auth/password`).
 */
export function FirstPasswordForm() {
  return (
    <PasswordChangeForm
      currentLabel={t.current}
      submitLabel={t.submit}
      // Rechargement complet : l'identité en cache disait encore « à changer ».
      onDone={() => window.location.replace("/dashboard")}
    >
      <button
        type="button"
        onClick={() => void logout().then(() => window.location.replace("/login"))}
        className="min-h-12 font-semibold text-encre-2 underline-offset-4 hover:underline"
      >
        {t.logout}
      </button>
    </PasswordChangeForm>
  );
}
