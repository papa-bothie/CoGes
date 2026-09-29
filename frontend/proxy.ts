import { NextResponse, type NextRequest } from "next/server";

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

  if (!hasSession && !onLogin) {
    const url = new URL("/login", request.url);
    if (pathname !== "/") url.searchParams.set("next", pathname + search);
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
