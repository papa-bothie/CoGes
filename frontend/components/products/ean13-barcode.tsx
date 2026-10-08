import { ean13Modules } from "@/lib/barcode/ean13";
import { labels } from "@/lib/labels";

/** Hauteur des barres, en modules ; les gardes descendent de 5 modules de plus. */
const BAR = 50;
const GUARD = 55;
/** Zones blanches imposées par la norme : 11 modules à gauche, 7 à droite. */
const QUIET_LEFT = 11;
const QUIET_RIGHT = 7;
const GUARD_MODULES = new Set([0, 1, 2, 45, 46, 47, 48, 49, 92, 93, 94]);

/**
 * Code-barres EAN-13 en SVG, à l'échelle de son conteneur. Noir sur blanc quel que soit le
 * thème : un lecteur lit un contraste, pas une couleur de marque. `null` si le code n'est
 * pas un EAN-13 valide.
 */
export function Ean13Barcode({ code, className }: { code: string; className?: string }) {
  const modules = ean13Modules(code);
  if (!modules) return null;
  const width = QUIET_LEFT + modules.length + QUIET_RIGHT;
  const digits = [code[0], code.slice(1, 7), code.slice(7)];
  return (
    <svg
      viewBox={`0 0 ${width} ${GUARD + 9}`}
      role="img"
      aria-label={labels.products.labelPage.barcodeOf(code)}
      className={className}
    >
      <rect width={width} height={GUARD + 9} className="fill-recu-papier" />
      {[...modules].map((bit, index) =>
        bit === "1" ? (
          <rect
            key={index}
            x={QUIET_LEFT + index}
            y={0}
            width={1}
            height={GUARD_MODULES.has(index) ? GUARD : BAR}
            className="fill-recu-encre"
          />
        ) : null,
      )}
      <g className="fill-recu-encre font-receipt" fontSize={9} textAnchor="middle">
        <text x={QUIET_LEFT - 4} y={GUARD + 8}>
          {digits[0]}
        </text>
        <text x={QUIET_LEFT + 24} y={GUARD + 8} letterSpacing={1.6}>
          {digits[1]}
        </text>
        <text x={QUIET_LEFT + 70} y={GUARD + 8} letterSpacing={1.6}>
          {digits[2]}
        </text>
      </g>
    </svg>
  );
}
