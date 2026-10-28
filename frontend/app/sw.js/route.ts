import { serviceWorkerSource } from "@/lib/pwa/sw-source";

/**
 * `/sw.js` à la racine du périmètre (ADR 0102), généré au build : l'identifiant de build
 * nomme le cache, et un nouveau build donne un nouveau worker, que le navigateur repère.
 * Jamais gardé longtemps : `no-cache`.
 */
export const dynamic = "force-static";

const BUILD = process.env.NEXT_DEPLOYMENT_ID || process.env.NEXT_PUBLIC_APP_VERSION || "dev";

export function GET(): Response {
  return new Response(serviceWorkerSource(BUILD), {
    headers: {
      "Content-Type": "text/javascript; charset=utf-8",
      "Cache-Control": "no-cache, no-store, must-revalidate",
      "Service-Worker-Allowed": "/",
    },
  });
}
