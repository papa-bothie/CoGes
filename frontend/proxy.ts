import { NextResponse, type NextRequest } from "next/server";

import { DEFAULT_NEXT, safeNext } from "@/lib/auth/safe-next";

/**
 * Redirection **de confort** entre la connexion et l'application. Le vrai contrôle est
 * fait par l'API à chaque appel (401 → rafraîchissement → retour à la connexion) : ce
 * fichier ne lit qu'un indicateur non sensible, `coges_session=1`, posé par le front.
 * Le cookie de rafraîchissement (chemin `/api/v1/auth`) ne lui parvient jamais.
 */
const SESSION_MARKER = "coges_session";

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const hasSession = request.cookies.get(SESSION_MARKER)?.value === "1";
  const onLogin = pathname === "/login";
  // Vitrine des composants (`/dev/composants`) : sans connexion, en développement seulement.
  // En production, la page elle-même répond 404.
  if (process.env.NODE_ENV !== "production" && pathname.startsWith("/dev/")) {
    return NextResponse.next();
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

export const config = {
  // Ni l'API réécrite, ni les ressources statiques.
  matcher: ["/((?!api/|_next/static|_next/image|favicon.ico|.*\\.(?:png|svg|ico|webp|txt)$).*)"],
};
