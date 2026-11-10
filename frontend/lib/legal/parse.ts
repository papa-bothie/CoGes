import { Lexer, type Token, type Tokens } from "marked";

/**
 * Textes légaux (prompt 36, ADR 0117) : chaque fichier de `content/legal/` commence par
 * `<!-- version: AAAA-MM-JJ -->`. La version n'est écrite que là : le front la lit ici, au
 * build, et le serveur garde la même date dans `LEGAL_VERSION` (un test backend les compare).
 */
const VERSION_LINE = /^<!-- version: (\d{4}-\d{2}-\d{2}) -->\r?\n/;

export type LegalDocument = {
  /** `AAAA-MM-JJ`, lue dans la première ligne du fichier. */
  version: string;
  /** Le titre de niveau 1 du texte. */
  title: string;
  /** Le reste du texte, en jetons `marked` (rendus en React, jamais en HTML brut). */
  tokens: Token[];
};

export function parseLegal(markdown: string, name = "texte"): LegalDocument {
  const match = VERSION_LINE.exec(markdown);
  if (!match) throw new Error(`${name} : la première ligne doit être <!-- version: AAAA-MM-JJ -->`);
  const version = match[1]!;
  if (Number.isNaN(Date.parse(`${version}T00:00:00Z`))) {
    throw new Error(`${name} : date de version invalide (${version})`);
  }
  const tokens = new Lexer({ gfm: true }).lex(markdown.slice(match[0].length));
  const index = tokens.findIndex((token) => token.type === "heading" && token.depth === 1);
  if (index < 0) throw new Error(`${name} : titre de niveau 1 absent`);
  const heading = tokens[index] as Tokens.Heading;
  return {
    version,
    title: heading.text,
    tokens: tokens.filter((_, position) => position !== index),
  };
}

/** `2026-12-01` → `01/12/2026` (format d'affichage du projet). */
export function displayVersion(version: string): string {
  const [year, month, day] = version.split("-");
  return `${day}/${month}/${year}`;
}
