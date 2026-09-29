import { redirect } from "next/navigation";

/** La racine n'a pas d'écran : `proxy.ts` oriente déjà vers la connexion au besoin. */
export default function Home() {
  redirect("/dashboard");
}
