import type { ReactNode } from "react";
import type { Token, Tokens } from "marked";

/**
 * Rendu en React des jetons `marked` d'un texte légal (ADR 0117) : aucun HTML brut, aucun
 * `dangerouslySetInnerHTML`. Les seules constructions admises sont celles des textes ; une
 * autre fait échouer le build, pour qu'un nouveau texte ne s'affiche jamais à moitié.
 */

function unsupported(type: string): never {
  throw new Error(`Texte légal : élément Markdown non pris en charge (${type})`);
}

function inline(tokens: Token[] | undefined, key = "i"): ReactNode[] {
  return (tokens ?? []).map((token, index) => {
    const id = `${key}-${index}`;
    switch (token.type) {
      case "text":
        return "tokens" in token && token.tokens ? (
          <span key={id}>{inline(token.tokens, id)}</span>
        ) : (
          decode((token as Tokens.Text).text)
        );
      case "escape":
        return (token as Tokens.Escape).text;
      case "strong":
        return (
          <strong key={id} className="font-bold text-foreground">
            {inline((token as Tokens.Strong).tokens, id)}
          </strong>
        );
      case "em":
        return <em key={id}>{inline((token as Tokens.Em).tokens, id)}</em>;
      case "codespan":
        return (
          <code key={id} className="rounded-mini bg-voile px-1.5 py-0.5 font-mono text-[0.9em]">
            {decode((token as Tokens.Codespan).text)}
          </code>
        );
      case "br":
        return <br key={id} />;
      case "link": {
        const link = token as Tokens.Link;
        const external = /^https?:/.test(link.href);
        return (
          <a
            key={id}
            href={link.href}
            {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
            className="font-semibold text-success-ink underline underline-offset-4"
          >
            {inline(link.tokens, id)}
          </a>
        );
      }
      default:
        return unsupported(token.type);
    }
  });
}

/** `marked` garde les entités de son échappement (`&#39;`, `&amp;`…) dans `text`. */
function decode(value: string): string {
  return value
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

function slug(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function table(token: Tokens.Table, id: string, caption: string | null): ReactNode {
  const align = (value: Tokens.TableCell["align"]) =>
    value === "right" ? "text-right" : value === "center" ? "text-center" : "text-left";
  return (
    // Défilement propre au tableau sur téléphone, jamais de la page (WCAG 1.4.10) ;
    // focalisable pour qu'on puisse le faire défiler au clavier.
    <div
      key={id}
      role="region"
      aria-label={caption ?? "Tableau"}
      tabIndex={0}
      className="overflow-x-auto rounded-carte border border-border outline-none focus-visible:ring-3 focus-visible:ring-ring/60"
    >
      <table className="w-full min-w-[480px] border-collapse text-left">
        <thead className="bg-voile">
          <tr>
            {token.header.map((cell, index) => (
              <th
                key={index}
                scope="col"
                className={`px-4 py-3 text-mini font-bold tracking-wide text-encre-2 uppercase ${align(cell.align)}`}
              >
                {inline(cell.tokens, `${id}-h${index}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {token.rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="border-t border-border align-top">
              {row.map((cell, index) => (
                <td key={index} className={`px-4 py-3 ${align(cell.align)}`}>
                  {inline(cell.tokens, `${id}-${rowIndex}-${index}`)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function LegalMarkdown({ tokens }: { tokens: Token[] }) {
  let section: string | null = null;
  const blocks: ReactNode[] = [];
  tokens.forEach((token, index) => {
    const id = `b-${index}`;
    switch (token.type) {
      case "space":
      case "html":
        // Lignes vides, commentaires (la ligne de version est déjà retirée).
        return;
      case "heading": {
        const heading = token as Tokens.Heading;
        section = heading.text;
        const anchor = slug(heading.text);
        const content = inline(heading.tokens, id);
        if (heading.depth === 2) {
          blocks.push(
            <h2
              key={id}
              id={anchor}
              className="scroll-mt-24 pt-6 text-[22px] leading-tight font-extrabold md:text-[26px]"
            >
              {content}
            </h2>,
          );
        } else if (heading.depth === 3) {
          blocks.push(
            <h3 key={id} id={anchor} className="scroll-mt-24 pt-2 text-libelle">
              {content}
            </h3>,
          );
        } else {
          unsupported(`titre de niveau ${heading.depth}`);
        }
        return;
      }
      case "paragraph":
        blocks.push(<p key={id}>{inline((token as Tokens.Paragraph).tokens, id)}</p>);
        return;
      case "list": {
        const list = token as Tokens.List;
        const items = list.items.map((item, itemIndex) => (
          <li key={itemIndex} className="pl-1">
            {inline(
              item.tokens.flatMap((child) => paragraphTokens(child)),
              `${id}-${itemIndex}`,
            )}
          </li>
        ));
        blocks.push(
          list.ordered ? (
            <ol key={id} className="list-decimal space-y-2 pl-6 marker:text-encre-2">
              {items}
            </ol>
          ) : (
            <ul key={id} className="list-disc space-y-2 pl-6 marker:text-encre-2">
              {items}
            </ul>
          ),
        );
        return;
      }
      case "table":
        blocks.push(table(token as Tokens.Table, id, section));
        return;
      case "hr":
        blocks.push(<hr key={id} className="border-border" />);
        return;
      default:
        unsupported(token.type);
    }
  });
  return <>{blocks}</>;
}

/** Un élément de liste « serré » porte des `text` ; « aéré », des paragraphes. */
function paragraphTokens(token: Token): Token[] {
  if (token.type === "paragraph") return (token as Tokens.Paragraph).tokens;
  if (token.type === "text") return [token];
  return unsupported(`${token.type} dans une liste`);
}
