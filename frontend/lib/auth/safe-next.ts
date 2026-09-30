/**
 * Destination après connexion (`?next=`), sans redirection ouverte (ADR 0049).
 *
 * Un simple test « commence par / » ne suffit pas : le navigateur lit `/\evil.example`
 * comme `//evil.example`, ignore tabulations et retours à la ligne dans une URL, et une
 * valeur comme `/.//evil.example` se normalise en `//evil.example`. On refuse donc les
 * caractères ambigus, on laisse le parseur d'URL du navigateur trancher, puis on n'accepte
 * que la **même origine** et un chemin qui ne peut pas être relu comme une autre origine.
 *
 * Utilisée partout où un `next` est lu ou construit : formulaire de connexion,
 * `loginUrl` (session expirée) et `proxy.ts`. Sans `window` : l'origine est fournie par
 * l'appelant, ce qui permet de l'appeler aussi côté serveur.
 */

export const DEFAULT_NEXT = "/dashboard";

// Antislash (lu comme « / » par les navigateurs) et caractères de contrôle C0 et DEL
// (supprimés silencieusement par le parseur d'URL).
const FORBIDDEN = /[\\\u0000-\u001f\u007f]/;

export function safeNext(next: string | null | undefined, origin: string): string {
  if (!next || FORBIDDEN.test(next)) return DEFAULT_NEXT;

  let url: URL;
  try {
    url = new URL(next, origin);
  } catch {
    return DEFAULT_NEXT;
  }

  if (url.origin !== new URL(origin).origin) return DEFAULT_NEXT;
  // Même origine, mais un chemin normalisé en `//hôte` repartirait ailleurs une fois
  // réutilisé comme URL relative (`location.assign("//evil.example")`).
  if (url.pathname.startsWith("//")) return DEFAULT_NEXT;
  if (url.pathname === "/login" || url.pathname.startsWith("/login/")) return DEFAULT_NEXT;

  return url.pathname + url.search + url.hash;
}
