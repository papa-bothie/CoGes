import { expect, test, type Page } from "@playwright/test";

import { ean13Modules } from "../lib/barcode/ean13";
import { E2E, loginThroughUi } from "./fixtures";

/**
 * Lecteur de la caméra sur un build de production (prompt 33, S0, ADR 0106).
 *
 * - WebKit (comme l'iPhone) n'a pas `BarcodeDetector` : la bibliothèque de lecture lit un
 *   EAN-13 montré à une fausse caméra, son moteur `.wasm` vient de la même origine, aucune
 *   requête ne sort, la CSP ne bloque rien.
 * - Chromium sans lecteur natif (Chrome pour Linux ne l'a pas, comme Firefox) : idem.
 * - Chromium avec un lecteur natif simulé (comme Chrome Android) : la bibliothèque n'est
 *   jamais téléchargée.
 */
test.describe.configure({ timeout: 120_000 });

const CODE = "4006381333931";

/** Fausse caméra : un canvas qui montre le code, rendu comme flux vidéo. */
async function fakeCamera(page: Page, modules: string, withNativeDetector: boolean) {
  await page.addInitScript(
    ({ modules, code, withNativeDetector }) => {
      const violations: string[] = [];
      (window as unknown as { __cspViolations: string[] }).__cspViolations = violations;
      document.addEventListener("securitypolicyviolation", (event) =>
        violations.push(`${event.violatedDirective} ${event.blockedURI}`),
      );
      const streams: MediaStream[] = [];
      (window as unknown as { __cameraStreams: MediaStream[] }).__cameraStreams = streams;
      const getUserMedia = async () => {
        const bar = 4;
        const canvas = document.createElement("canvas");
        canvas.width = (modules.length + 22) * bar;
        canvas.height = 240;
        const context = canvas.getContext("2d")!;
        const draw = () => {
          context.fillStyle = "#fff";
          context.fillRect(0, 0, canvas.width, canvas.height);
          context.fillStyle = "#000";
          [...modules].forEach((bit, index) => {
            if (bit === "1") context.fillRect((index + 11) * bar, 20, bar, 200);
          });
        };
        draw();
        window.setInterval(draw, 100);
        const stream = canvas.captureStream(10);
        streams.push(stream);
        return stream;
      };
      Object.defineProperty(navigator, "mediaDevices", {
        configurable: true,
        value: { getUserMedia },
      });
      if (withNativeDetector) {
        // Lecteur natif simulé : il « lit » le code dès que la vidéo tourne.
        class NativeDetector {
          async detect(video: HTMLVideoElement) {
            return video.readyState >= 2 ? [{ rawValue: code }] : [];
          }
        }
        (window as unknown as { BarcodeDetector: unknown }).BarcodeDetector = NativeDetector;
      }
    },
    { modules, code: CODE, withNativeDetector },
  );
}

async function scanOnNewProduct(page: Page) {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  await page.goto("/products/new");
  await page.getByRole("button", { name: "Scanner le code-barres" }).click();
  await expect(page.getByText(`Code-barres : ${CODE}`)).toBeVisible({ timeout: 30_000 });
  // La caméra est coupée dès que le code est lu.
  await expect
    .poll(() =>
      page.evaluate(() =>
        (window as unknown as { __cameraStreams: MediaStream[] }).__cameraStreams
          .flatMap((stream) => stream.getTracks())
          .every((track) => track.readyState === "ended"),
      ),
    )
    .toBe(true);
  const violations = await page.evaluate(
    () => (window as unknown as { __cspViolations: string[] }).__cspViolations,
  );
  return { requests, violations };
}

// WebKit comme l'iPhone ; Chromium sans lecteur natif comme Firefox (Chrome pour Linux ne l'a pas).
test("sans lecteur natif : la bibliothèque lit le code, servie par CoGes, sans rien bloquer", async ({
  page,
  baseURL,
}) => {
  const modules = ean13Modules(CODE)!;
  await fakeCamera(page, modules, false);
  const { requests, violations } = await scanOnNewProduct(page);

  expect(await page.evaluate(() => "BarcodeDetector" in window)).toBe(false);
  const origin = new URL(baseURL!).origin;
  const wasm = requests.filter((url) => url.includes(".wasm"));
  expect(wasm).toHaveLength(1);
  expect(wasm[0]).toMatch(
    new RegExp(`^${origin}/_next/static/media/zxing_reader\\.[^/?]+\\.wasm(\\?dpl=[^&]+)?$`),
  );
  expect(requests.filter((url) => !url.startsWith(origin) && !url.startsWith("data:"))).toEqual([]);
  expect(violations).toEqual([]);

  // Poids et temps du premier chargement du moteur, repris dans l'ADR 0106.
  const engine = await page.evaluate(() => {
    const entry = performance
      .getEntriesByType("resource")
      .find((item) => item.name.includes("zxing_reader")) as PerformanceResourceTiming;
    return {
      ms: Math.round(entry.duration),
      bytes: entry.transferSize,
      body: entry.decodedBodySize,
    };
  });
  test.info().annotations.push({ type: "moteur", description: JSON.stringify(engine) });
  console.log(`moteur ${test.info().project.name} : ${JSON.stringify(engine)}`);
});

test("lecteur natif : il sert, la bibliothèque n'est pas chargée", async ({
  page,
  browserName,
}) => {
  test.skip(browserName !== "chromium", "lecteur natif : Chromium seulement");
  const modules = ean13Modules(CODE)!;
  await fakeCamera(page, modules, true);
  const scripts: Promise<string>[] = [];
  page.on("response", (response) => {
    if (response.request().resourceType() === "script") {
      scripts.push(response.text().catch(() => ""));
    }
  });
  const { requests, violations } = await scanOnNewProduct(page);

  expect(requests.filter((url) => url.includes(".wasm"))).toEqual([]);
  // Le code de la bibliothèque n'a pas été téléchargé non plus : « AllReadable » est un nom
  // de sa table des formats, qu'aucun autre script ne porte.
  const bodies = await Promise.all(scripts);
  expect(bodies.length).toBeGreaterThan(0);
  expect(bodies.some((text) => text.includes("AllReadable"))).toBe(false);
  expect(violations).toEqual([]);
});
