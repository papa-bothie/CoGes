import Image from "next/image";

import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

/**
 * Logo officiel (docs/design/maquette-v2/logo/, ADR 0064). En clair, l'image telle quelle ;
 * en sombre, sa silhouette dans le vert de marque éclairci (`bg-marque`) : le vert foncé du
 * logo disparaîtrait sur un fond sombre.
 */
function BrandImage({
  src,
  alt,
  width,
  height,
  className,
  eager = false,
}: {
  src: string;
  alt: string;
  width: number;
  height: number;
  className?: string;
  /** Logo au-dessus de la ligne de flottaison : chargé tout de suite. */
  eager?: boolean;
}) {
  return (
    <>
      <Image
        src={src}
        alt={alt}
        width={width}
        height={height}
        unoptimized
        loading={eager ? "eager" : undefined}
        style={{ width, height }}
        className={cn("block shrink-0 dark:hidden", className)}
      />
      <span
        role={alt ? "img" : undefined}
        aria-label={alt || undefined}
        aria-hidden={alt ? undefined : true}
        className={cn("hidden shrink-0 bg-marque dark:block", className)}
        style={{
          width,
          height,
          maskImage: `url(${src})`,
          maskSize: "contain",
          maskRepeat: "no-repeat",
          WebkitMaskImage: `url(${src})`,
          WebkitMaskSize: "contain",
          WebkitMaskRepeat: "no-repeat",
        }}
      />
    </>
  );
}

/** Le symbole seul, 40 × 43 px : barre du haut, barre latérale. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <BrandImage
      src="/brand/coges-mark.png"
      alt=""
      width={40}
      height={43}
      className={className}
      eager
    />
  );
}

/** Le nom « CoGes », 24 px de haut. */
export function BrandWordmark({ className }: { className?: string }) {
  return (
    <BrandImage
      src="/brand/coges-wordmark.png"
      alt={labels.app.name}
      width={102}
      height={24}
      className={className}
      eager
    />
  );
}

/** Symbole + nom + nom de la boutique dessous : en-tête de l'application. */
export function BrandHeader({ companyName }: { companyName: string }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <BrandMark />
      <div className="min-w-0">
        <BrandWordmark />
        <p className="truncate text-sm text-muted-foreground" title={companyName}>
          {companyName}
        </p>
      </div>
    </div>
  );
}

/** Le logo complet avec « Votre entreprise sous contrôle » : écran de connexion. */
export function BrandLogo({ className }: { className?: string }) {
  return (
    <BrandImage
      src="/brand/coges-logo.png"
      alt={`${labels.app.name}, ${labels.app.tagline}`}
      width={262}
      height={77}
      className={className}
      eager
    />
  );
}
