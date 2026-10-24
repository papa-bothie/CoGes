import { NextResponse, type NextRequest } from "next/server";

/**
 * Redirection **de confort** seulement : le vrai contrôle est fait par l'API à chaque
 * appel. Ce fichier ne lit qu'un indicateur non sensible, `coges_admin_session=1`.
 */
const SESSION_MARKER = "coges_admin_session";

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession = request.cookies.get(SESSION_MARKER)?.value === "1";
  const onLogin = pathname === "/login";
  // Le lien d'invitation s'ouvre sans session : le collègue n'a pas encore de compte.
  const onInvitation = pathname.startsWith("/invitation/");
  if (onInvitation) return NextResponse.next();
  if (!hasSession && !onLogin) return NextResponse.redirect(new URL("/login", request.url));
  if (hasSession && onLogin) return NextResponse.redirect(new URL("/", request.url));
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api/|_next/static|_next/image|favicon.ico|.*\\.(?:png|svg|ico|txt)$).*)"],
};
