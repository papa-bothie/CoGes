import { NextResponse, type NextRequest } from "next/server";

import { VITRINE_FILES } from "@/content/vitrine-files";
import { KNOWN_MARKER, KNOWN_MAX_AGE_SECONDS } from "@/lib/auth/known";
import { DEFAULT_NEXT, safeNext } from "@/lib/auth/safe-next";

/**
 * Redirection **de confort** entre la connexion et l'application. Le vrai contrôle est
 * fait par l'API à chaque appel (401 → rafraîchissement → retour à la connexion) : ce
 * fichier ne lit qu'un indicateur non sensible, `coges_session=1`, posé par le front.
 * Le cookie de rafraîchissement (chemin `/api/v1/auth`) ne lui parvient jamais.
 *
 * Racine (prompt 37, ADR 0115) : la vitrine n'est montrée qu'à un visiteur **nouveau**, sans
 * session ni marqueur `coges_known=1` (« quelqu'un s'est déjà connecté sur cet appareil »).
 * Un commerçant dont la session a expiré arrive donc sur la connexion, comme avant.
 */
const SESSION_MARKER = "coges_session";
const PUBLIC_PWA = new Set(["/manifest.webmanifest", "/sw.js", "/hors-ligne"]);
// Routes publiques de la vitrine, nommées une à une (jamais un motif large) ; les textes
// légaux s'ouvrent sans connexion (prompt 36, ADR 0117).
const PUBLIC_VITRINE = new Set([
  "/conditions",
  "/confidentialite",
  "/robots.txt",
  "/sitemap.xml",
  ...VITRINE_FILES.map((name) => `/vitrine/${name}`),
]);

function isPublic(pathname: string): boolean {
  // Application installable (ADR 0102) : manifeste, worker et page hors ligne répondent sans
  // connexion, sans jamais renvoyer vers /login.
  if (PUBLIC_PWA.has(pathname) || PUBLIC_VITRINE.has(pathname)) return true;
  // Inscription libre-service (ADR 0118) : le formulaire, et le lien de l'e-mail, dont le
  // jeton est le seul segment variable (les pages répondent 404 si l'inscription est fermée).
  if (pathname === "/inscription" || pathname === "/verification") return true;
  if (/^\/verification\/[A-Za-z0-9_-]{20,200}$/.test(pathname)) return true;
  // Accès support (ADR 0092) : l'entrée lit le jeton du fragment, la fin le dit.
  return pathname === "/support" || pathname === "/support/termine";
}

function route(request: NextRequest, hasSession: boolean, known: boolean): NextResponse {
  const { pathname, search } = request.nextUrl;
  const onLogin = pathname === "/login";

  // Vitrine des composants (`/dev/composants`) : sans connexion, en développement seulement.
  // En production, la page elle-même répond 404.
  if (process.env.NODE_ENV !== "production" && pathname.startsWith("/dev/")) {
    return NextResponse.next();
  }
  if (isPublic(pathname)) return NextResponse.next();

  if (pathname === "/") {
    if (hasSession) return NextResponse.redirect(new URL("/dashboard", request.url));
    if (known) return NextResponse.redirect(new URL("/login", request.url));
    return NextResponse.next(); // visiteur nouveau : la vitrine
  }

  if (!hasSession && !onLogin) {
    const url = new URL("/login", request.url);
    // Même contrôle qu'au retour de la connexion : on ne propage jamais un `next` douteux.
    const next = safeNext(pathname + search, request.nextUrl.origin);
    if (next !== DEFAULT_NEXT) url.searchParams.set("next", next);
    return NextResponse.redirect(url);
  }
  if (hasSession && onLogin) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  return NextResponse.next();
}

export function proxy(request: NextRequest) {
  const hasSession = request.cookies.get(SESSION_MARKER)?.value === "1";
  const known = request.cookies.get(KNOWN_MARKER)?.value === "1";
  const response = route(request, hasSession, known);
  // Les comptes déjà connectés reçoivent le marqueur à leur prochaine visite, sans rien faire.
  if (hasSession) {
    response.cookies.set(KNOWN_MARKER, "1", {
      path: "/",
      maxAge: KNOWN_MAX_AGE_SECONDS,
      sameSite: "lax",
      secure: request.nextUrl.protocol === "https:",
    });
  }
  return response;
}

export const config = {
  // Ni l'API réécrite, ni les ressources statiques (images, polices, robots.txt, sitemap.xml).
  matcher: [
    "/((?!api/|_next/static|_next/image|favicon.ico|.*\\.(?:png|svg|ico|webp|avif|jpg|jpeg|woff2|txt|xml)$).*)",
  ],
};
