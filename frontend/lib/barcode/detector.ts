/**
 * Lecteur de code-barres de la caméra (prompt 33, ADR 0106).
 *
 * Chrome Android, Chrome et Edge ont l'API native `BarcodeDetector` : elle sert telle quelle,
 * et rien d'autre n'est téléchargé. iPhone (Safari) et Firefox ne l'ont pas : la bibliothèque
 * `barcode-detector` (ZXing-C++ en WebAssembly, même API) est alors chargée à la demande. Son
 * moteur `.wasm` est servi par CoGes, sous `/_next/static/media/` (empreinte dans le nom, gardé
 * par le service worker comme tout fichier statique) : jamais depuis un CDN.
 */

export type Detected = { rawValue: string };
export type Detector = { detect: (source: HTMLVideoElement) => Promise<Detected[]> };
export type DetectorConstructor = new (options: { formats: string[] }) => Detector;

export const FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128"];

export function nativeDetector(): DetectorConstructor | null {
  if (typeof window === "undefined") return null;
  const candidate = (window as unknown as { BarcodeDetector?: DetectorConstructor })
    .BarcodeDetector;
  return candidate ?? null;
}

let library: Promise<DetectorConstructor> | null = null;

/** Le moteur de la bibliothèque, chargé une fois par page ; un échec permet de réessayer. */
function loadLibrary(): Promise<DetectorConstructor> {
  library ??= (async () => {
    const { BarcodeDetector, prepareZXingModule } = await import("barcode-detector/ponyfill");
    // Résolu par le bundler : le fichier est copié dans le build, à la même origine.
    const wasm = new URL("zxing-wasm/reader/zxing_reader.wasm", import.meta.url).href;
    await prepareZXingModule({
      overrides: {
        locateFile: (path: string, prefix: string) =>
          path.endsWith(".wasm") ? wasm : prefix + path,
      },
      fireImmediately: true,
    });
    return BarcodeDetector as unknown as DetectorConstructor;
  })().catch((error: unknown) => {
    library = null;
    throw error;
  });
  return library;
}

/** Le lecteur qui servira : natif, ou la bibliothèque à charger. */
export function detectorSource(): "native" | "library" {
  return nativeDetector() ? "native" : "library";
}

export async function loadDetector(): Promise<DetectorConstructor> {
  return nativeDetector() ?? loadLibrary();
}
