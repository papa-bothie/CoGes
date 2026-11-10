import { readdirSync } from "node:fs";
import { join } from "node:path";

import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { VITRINE_FILES } from "@/content/vitrine-files";
import { KNOWN_MARKER } from "@/lib/auth/known";

import { config, proxy } from "./proxy";

type Cookies = { session?: boolean; known?: boolean };

const visit = (path: string, cookies: Cookies = {}) => {
  const request = new NextRequest(new URL(path, "https://coges.app"));
  if (cookies.session) request.cookies.set("coges_session", "1");
  if (cookies.known) request.cookies.set(KNOWN_MARKER, "1");
  return proxy(request);
};

/** `null` : la page demandée est servie ; sinon le chemin de la redirection. */
function outcome(response: Response): string | null {
  const location = response.headers.get("location");
  if (!location) return null;
  const url = new URL(location);
  return url.pathname + url.search;
}

const IMAGE = `/vitrine/${VITRINE_FILES[0]}`;

describe("proxy : application installable (ADR 0102)", () => {
  it.each(["/manifest.webmanifest", "/sw.js", "/hors-ligne"])(
    "%s répond sans connexion ni redirection",
    (path) => {
      const response = visit(path);
      expect(response.headers.get("location")).toBeNull();
      expect(response.status).toBe(200);
    },
  );

  it("une page de l'application, elle, renvoie toujours vers la connexion", () => {
    const response = visit("/dashboard");
    expect(response.headers.get("location")).toContain("/login");
  });
});

/**
 * Arbre de décision de la racine (prompt 37, ADR 0115) : la vitrine n'est montrée qu'à un
 * visiteur nouveau, sans session ET jamais connecté sur cet appareil.
 */
describe("proxy : vitrine et commerçant de retour (ADR 0115)", () => {
  const NONE: Cookies = {};
  const KNOWN: Cookies = { known: true };
  const SESSION: Cookies = { session: true, known: true };
  const SESSION_ONLY: Cookies = { session: true };

  // [route, cookies, résultat attendu]
  const table: [string, Cookies, string | null][] = [
    ["/", NONE, null],
    ["/", KNOWN, "/login"],
    ["/", SESSION, "/dashboard"],
    ["/", SESSION_ONLY, "/dashboard"],
    ["/login", NONE, null],
    ["/login", KNOWN, null],
    ["/login", SESSION, "/dashboard"],
    ["/dashboard", NONE, "/login"],
    ["/dashboard", KNOWN, "/login"],
    ["/dashboard", SESSION, null],
    ["/sales/new", NONE, "/login?next=%2Fsales%2Fnew"],
    ["/support", NONE, null],
    ["/support", SESSION, null],
    ["/hors-ligne", NONE, null],
    ["/manifest.webmanifest", NONE, null],
    ["/sw.js", NONE, null],
    ["/sitemap.xml", NONE, null],
    ["/sitemap.xml", KNOWN, null],
    ["/robots.txt", NONE, null],
    [IMAGE, NONE, null],
    [IMAGE, KNOWN, null],
    // Textes légaux (prompt 36, ADR 0117) : sans connexion, connu ou non, connecté aussi.
    ["/conditions", NONE, null],
    ["/conditions", KNOWN, null],
    ["/conditions", SESSION, null],
    ["/confidentialite", NONE, null],
    ["/confidentialite", KNOWN, null],
    // Inscription libre-service (ADR 0118) : sans connexion ; le lien, à son seul format.
    ["/inscription", NONE, null],
    ["/inscription", KNOWN, null],
    ["/verification", NONE, null],
    ["/verification/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde", NONE, null],
    ["/verification/court", NONE, "/login?next=%2Fverification%2Fcourt"],
    ["/verification/a/b", NONE, "/login?next=%2Fverification%2Fa%2Fb"],
    // L'écran d'acceptation, lui, exige une session.
    ["/acceptation", NONE, "/login?next=%2Facceptation"],
    ["/acceptation", SESSION, null],
  ];

  it.each(table)("%s avec %j → %s", (path, cookies, expected) => {
    expect(outcome(visit(path, cookies))).toBe(expected);
  });

  it("une route voisine de la vitrine n'est pas publique par ressemblance", () => {
    expect(outcome(visit("/vitrine/inconnu.webp"))).toContain("/login");
    expect(outcome(visit("/vitrine"))).toContain("/login");
    expect(outcome(visit("/robots.txt/x"))).toContain("/login");
    expect(outcome(visit("/conditions/x"))).toContain("/login");
    expect(outcome(visit("/confidentialites"))).toContain("/login");
  });

  it("pose coges_known sur toute réponse qui porte coges_session=1", () => {
    for (const path of ["/", "/dashboard", "/login", "/sw.js"]) {
      const cookie = visit(path, SESSION_ONLY).headers.get("set-cookie") ?? "";
      expect(cookie).toContain(`${KNOWN_MARKER}=1`);
      expect(cookie).toMatch(/Max-Age=31536000/i);
      expect(cookie).toMatch(/SameSite=lax/i);
      expect(cookie).toMatch(/Path=\//i);
      expect(cookie).toMatch(/Secure/i);
      expect(cookie).not.toMatch(/HttpOnly/i);
    }
  });

  it("ne pose aucun cookie sans session, et rien d'autre que coges_known=1", () => {
    expect(visit("/").headers.get("set-cookie")).toBeNull();
    expect(visit("/", KNOWN).headers.get("set-cookie")).toBeNull();
    const cookie = visit("/dashboard", SESSION_ONLY).headers.get("set-cookie") ?? "";
    // Une seule paire nom=valeur, sans identifiant.
    const pairs = cookie.split(/,(?=\s*[^;=]+=)/).map((part) => (part.split(";")[0] ?? "").trim());
    expect(pairs).toEqual([`${KNOWN_MARKER}=1`]);
  });
});

describe("proxy : matcher", () => {
  const matcher = new RegExp(`^${config.matcher[0]}$`);

  it.each([
    "/vitrine/a.webp",
    "/vitrine/a.avif",
    "/x.jpg",
    "/x.jpeg",
    "/f.woff2",
    "/x.svg",
    "/sitemap.xml",
    "/robots.txt",
    "/vitrine/partage.png",
  ])("%s ne passe pas par le proxy (fichier statique)", (path) => {
    expect(matcher.test(path)).toBe(false);
  });

  it.each(["/", "/login", "/dashboard", "/sales/new", "/hors-ligne", "/manifest.webmanifest"])(
    "%s passe par le proxy",
    (path) => {
      expect(matcher.test(path)).toBe(true);
    },
  );
});

describe("fichiers de la vitrine", () => {
  it("la liste fermée nomme exactement le contenu de public/vitrine/", () => {
    const onDisk = readdirSync(join(__dirname, "public", "vitrine")).sort();
    expect([...VITRINE_FILES].sort()).toEqual(onDisk);
  });
});
