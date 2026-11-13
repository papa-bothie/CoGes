import { expect, test, type Page } from "@playwright/test";

import { texte } from "../content/vitrine-texte";

/**
 * Animations de la vitrine (prompt 38, ADR 0116). Les animations CSS ne suivent pas
 * `page.clock` : on les arrête et on règle leur `currentTime` (Web Animations), ce qui
 * place la séquence à l'instant voulu sans aucune attente réelle.
 */
const WIDTHS = [
  [360, 740],
  [768, 1024],
  [1280, 800],
] as const;

/** Attend que les animations du titre existent (premier rendu fait). */
async function ready(page: Page) {
  await page.goto("/");
  await page.waitForFunction(
    () => document.querySelector("[data-zone]")!.getAnimations({ subtree: true }).length > 0,
  );
}

/** Place toutes les animations à horloge (titre, halo, éclat, apparitions) à `ms`. */
async function seek(page: Page, ms: number) {
  await page.evaluate((time) => {
    for (const animation of document.getAnimations()) {
      if (animation.timeline !== document.timeline) continue; // défilement : pas d'horloge
      animation.pause();
      animation.currentTime = time;
    }
  }, ms);
}

/** Opacité de chaque élément de la zone : les trois mots, puis la phrase complète. */
async function opacities(page: Page): Promise<Record<string, number>> {
  return page.evaluate(() => {
    const result: Record<string, number> = {};
    for (const element of document.querySelectorAll<HTMLElement>("[data-zone] > *")) {
      const key = element.dataset.mot ?? "complet";
      result[key] = Number(getComputedStyle(element).opacity);
    }
    return result;
  });
}

function visibleOnly(state: Record<string, number>): string[] {
  return Object.entries(state)
    .filter(([, opacity]) => opacity > 0.99)
    .map(([key]) => key);
}

/** Étapes de la mini-caisse entièrement visibles (lignes 1 à 3, total, « Encaissé »). */
async function caisseVisible(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>("[data-caisse-etape]")]
      .filter((element) => Number(getComputedStyle(element).opacity) > 0.99)
      .map((element) => element.dataset.caisseEtape!),
  );
}

/** Révèle toute la page (défilement) et termine les animations finies d'apparition. */
async function scrollThrough(page: Page) {
  const height = await page.evaluate(() => document.body.scrollHeight);
  for (let y = 0; y <= height; y += 400) {
    await page.evaluate((top) => window.scrollTo(0, top), y);
    await page.waitForTimeout(30);
  }
}

test.describe("vitrine : titre qui change de mot", () => {
  test("trois mots relayés, puis la phrase complète et plus aucune animation", async ({ page }) => {
    await ready(page);
    await seek(page, 0);
    expect(visibleOnly(await opacities(page))).toEqual(["Les ventes"]);
    await seek(page, 3200);
    expect(visibleOnly(await opacities(page))).toEqual(["Le stock"]);
    await seek(page, 6200);
    expect(visibleOnly(await opacities(page))).toEqual(["L'argent"]);
    // Deuxième et troisième tours.
    await seek(page, 9200);
    expect(visibleOnly(await opacities(page))).toEqual(["Les ventes"]);
    await seek(page, 24200);
    expect(visibleOnly(await opacities(page))).toEqual(["L'argent"]);
    // Pendant le relais, un mot sort pendant que le suivant entre.
    await seek(page, 2800);
    const relay = await opacities(page);
    expect(relay["Les ventes"]).toBeGreaterThan(0);
    expect(relay["Les ventes"]).toBeLessThan(1);
    expect(relay["Le stock"]).toBeGreaterThan(0);
    expect(relay["Le stock"]).toBeLessThan(1);

    await seek(page, 28_000);
    expect(visibleOnly(await opacities(page))).toEqual(["complet"]);
    await expect(page.locator("[data-complet]")).toHaveText(texte.hero.rotation.complet);
    // Relancées au-delà de leur fin, les animations se terminent : il n'en reste aucune.
    await page.evaluate(() => {
      for (const animation of document.getAnimations()) {
        if (animation.timeline === document.timeline) animation.play();
      }
    });
    expect(
      await page.evaluate(
        () => document.querySelector("[data-zone]")!.getAnimations({ subtree: true }).length,
      ),
    ).toBe(0);
  });

  test("toutes les animations de la vitrine ont une fin, la dernière vers 27 s", async ({
    page,
  }) => {
    await ready(page);
    const ends = await page.evaluate(() =>
      document
        .getAnimations()
        .filter((animation) => animation.timeline === document.timeline)
        .map((animation) => Number(animation.effect!.getComputedTiming().endTime)),
    );
    expect(ends.length).toBeGreaterThan(0);
    for (const end of ends) expect(Number.isFinite(end)).toBe(true);
    // Fin du titre : 27 s (−0,4 s de délai + 3 tours de 9 s + la sortie de « L'argent »).
    const title = await page.evaluate(() =>
      document
        .querySelector("[data-zone]")!
        .getAnimations({ subtree: true })
        .map((animation) => Number(animation.effect!.getComputedTiming().endTime)),
    );
    expect(Math.max(...title)).toBeCloseTo(27_000, -2);
  });

  test("le h1 porte la phrase complète en texte réel, la version animée est cachée", async ({
    page,
  }) => {
    await page.goto("/");
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toHaveAccessibleName(texte.hero.title);
    await expect(heading).toHaveAttribute("id", "titre");
    await expect(heading.locator(".sr-only")).toHaveText(texte.hero.title);
    await expect(heading.locator("[aria-hidden]")).toHaveCount(1);
    await expect(page.locator("section[aria-labelledby=titre]")).toHaveCount(1);
  });

  test("pause au survol et au focus clavier", async ({ page }) => {
    await ready(page);
    const states = () =>
      page.evaluate(() => [
        ...new Set(
          document
            .querySelector("[data-zone]")!
            .getAnimations({ subtree: true })
            .map((animation) => animation.playState),
        ),
      ]);
    expect(await states()).toEqual(["running"]);
    await page.locator("[data-zone]").hover();
    expect(await states()).toEqual(["paused"]);
    await page.mouse.move(0, 0);
    expect(await states()).toEqual(["running"]);
    // Au clavier : le focus sur un bouton du hero arrête aussi la séquence.
    await page
      .getByRole("main")
      .getByRole("link", { name: /Écrire sur WhatsApp/ })
      .first()
      .focus();
    expect(await states()).toEqual(["paused"]);
  });

  test("le mot relayé a un contraste AA, en clair et en sombre", async ({ page }) => {
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto("/");
      const ratio = await page.evaluate(() => {
        /** Luminance relative WCAG d'une couleur `rgb(r, g, b)` calculée. */
        const luminance = (value: string): number => {
          const [r = 0, g = 0, b = 0] = (value.match(/[\d.]+/g) ?? []).map((channel) => {
            const c = Number(channel) / 255;
            return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
          });
          return 0.2126 * r + 0.7152 * g + 0.0722 * b;
        };
        const word = luminance(getComputedStyle(document.querySelector("[data-mot]")!).color);
        const back = luminance(getComputedStyle(document.body).backgroundColor);
        const [a, b] = [Math.max(word, back), Math.min(word, back)];
        return (a + 0.05) / (b + 0.05);
      });
      expect(ratio, scheme).toBeGreaterThanOrEqual(4.5);
    }
  });
});

test.describe("vitrine : mini-caisse du hero (A9)", () => {
  test("trois articles un par un, le total, puis « Encaissé », une seule fois", async ({
    page,
  }) => {
    // Les lignes jouent dès 0,5 s : sous charge, la première avait fini (et quitté
    // `getAnimations`) avant que le test ne la mette en pause. Horloge des animations
    // ralentie vingt fois le temps de la prendre en main ; `seek` place ensuite chaque instant.
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Animation.enable");
    await cdp.send("Animation.setPlaybackRate", { playbackRate: 0.05 });
    await ready(page);
    // Moins de 5 s en tout (WCAG 2.2.2 : rien à mettre en pause), puis plus rien.
    const ends = await page.evaluate(() =>
      document
        .querySelector("[data-caisse]")!
        .getAnimations({ subtree: true })
        .map((animation) => Number(animation.effect!.getComputedTiming().endTime)),
    );
    expect(ends.length).toBeGreaterThan(0);
    expect(Math.max(...ends)).toBeLessThan(5000);
    const steps: [number, string[]][] = [
      [0, []],
      [1000, ["1"]],
      [2000, ["1", "2", "3"]],
      [2700, ["1", "2", "3", "total"]],
      [3400, ["1", "2", "3", "total", "encaisse"]],
    ];
    for (const [ms, expected] of steps) {
      await seek(page, ms);
      expect(await caisseVisible(page), `à ${ms} ms`).toEqual(expected);
    }
    await seek(page, 5000);
    await page.evaluate(() => {
      for (const animation of document.getAnimations()) {
        if (animation.timeline === document.timeline) animation.finish();
      }
    });
    expect(
      await page.evaluate(
        () => document.querySelector("[data-caisse]")!.getAnimations({ subtree: true }).length,
      ),
    ).toBe(0);
    expect(await caisseVisible(page)).toEqual(["1", "2", "3", "total", "encaisse"]);
  });

  test("cachée aux lecteurs d'écran, avec un texte équivalent ; plus d'illustration", async ({
    page,
  }) => {
    await page.goto("/");
    const caisse = page.locator("[data-caisse]");
    await expect(caisse).toHaveAttribute("aria-hidden", "true");
    await expect(page.locator("section[aria-labelledby=titre] .sr-only").last()).toHaveText(
      texte.hero.caisse.resume,
    );
    await expect(page.locator("section[aria-labelledby=titre] img")).toHaveCount(0);
    for (const ligne of texte.hero.caisse.lignes) await expect(caisse).toContainText(ligne.article);
    await expect(caisse).toContainText("21\u00a0000\u00a0F");
  });
});

test.describe("vitrine : aucun décalage de mise en page", () => {
  for (const scheme of ["light", "dark"] as const) {
    for (const [width, height] of WIDTHS) {
      test(`CLS = 0 à ${width} px (${scheme === "light" ? "clair" : "sombre"})`, async ({
        page,
      }) => {
        await page.emulateMedia({ colorScheme: scheme });
        await page.setViewportSize({ width, height });
        await ready(page);
        // Compté une fois les polices prêtes : le passage de la police de secours à Figtree
        // (mise en page racine, hors de ce lot ; ADR 0116, « Suites ») n'est pas une animation.
        await page.evaluate(async () => {
          await document.fonts.ready;
          const win = window as unknown as { __cls: number };
          win.__cls = 0;
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries() as unknown as {
              value: number;
              hadRecentInput: boolean;
            }[]) {
              if (!entry.hadRecentInput) win.__cls += entry.value;
            }
          }).observe({ type: "layout-shift" });
        });
        // Le titre garde la même boîte à chaque instant de la séquence.
        const boxes = new Set<string>();
        for (const ms of [0, 1500, 2800, 3200, 6200, 26_800, 28_000]) {
          await seek(page, ms);
          const box = await page.locator("#titre").boundingBox();
          const zone = await page.locator("[data-zone]").boundingBox();
          const caisse = await page.locator("[data-caisse]").boundingBox();
          boxes.add(JSON.stringify([box, zone, caisse]));
        }
        expect(boxes.size).toBe(1);
        // Aucun mot ne passe à la ligne : chacun tient sur une ligne à toute largeur.
        const lines = await page.evaluate(() =>
          [...document.querySelectorAll<HTMLElement>("[data-mot]")].map(
            (element) => element.getClientRects().length,
          ),
        );
        expect(lines).toEqual([1, 1, 1]);
        await page.evaluate(() => {
          for (const animation of document.getAnimations()) {
            if (animation.timeline === document.timeline) animation.play();
          }
        });
        await scrollThrough(page);
        await page.waitForTimeout(800);
        const shifts = await page.evaluate(() => (window as unknown as { __cls: number }).__cls);
        expect(shifts).toBe(0);
        // Le halo ne crée aucun défilement horizontal.
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
        ).toBeLessThanOrEqual(0);
      });
    }
  }
});

test.describe("vitrine : apparitions au défilement", () => {
  for (const [width, height] of [...WIDTHS, [1440, 900] as const]) {
    test(`rien de ce qui est visible au premier affichage n'est masqué (${width} px)`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height });
      await page.goto("/");
      const above = await page.evaluate(() =>
        [...document.querySelectorAll("[data-revele]")]
          .filter((element) => element.getBoundingClientRect().top < window.innerHeight)
          .map((element) => element.textContent?.slice(0, 40)),
      );
      expect(above).toEqual([]);
    });
  }

  test("chaque élément marqué paraît une fois arrivé à l'écran", async ({ page }) => {
    await page.goto("/");
    const marked = page.locator("[data-revele]");
    expect(await marked.count()).toBeGreaterThan(10);
    await expect(page.locator("[data-revele][data-vu]")).toHaveCount(0);
    await scrollThrough(page);
    await expect(page.locator("[data-revele]:not([data-vu])")).toHaveCount(0);
    await page.evaluate(() => {
      for (const animation of document.getAnimations()) {
        if (animation.timeline === document.timeline) animation.finish();
      }
    });
    const hidden = await page.evaluate(
      () =>
        [...document.querySelectorAll("[data-revele]")].filter(
          (element) => getComputedStyle(element).opacity !== "1",
        ).length,
    );
    expect(hidden).toBe(0);
  });
});

test.describe("vitrine : mouvement réduit", () => {
  test.use({ reducedMotion: "reduce" });

  test("phrase complète tout de suite, rien ne bouge, tout est visible", async ({ page }) => {
    await page.goto("/");
    expect(visibleOnly(await opacities(page))).toEqual(["complet"]);
    await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName(texte.hero.title);
    expect(await page.evaluate(() => document.getAnimations().length)).toBe(0);
    expect(await caisseVisible(page)).toEqual(["1", "2", "3", "total", "encaisse"]);
    // Avant tout défilement, les sections plus bas sont déjà visibles.
    const hidden = await page.evaluate(
      () =>
        [...document.querySelectorAll("[data-revele]")].filter(
          (element) => getComputedStyle(element).opacity !== "1",
        ).length,
    );
    expect(hidden).toBe(0);
    await scrollThrough(page);
    expect(await page.evaluate(() => document.getAnimations().length)).toBe(0);
  });
});

test.describe("vitrine : sans JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("tout le contenu est visible et le titre complet lisible", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName(texte.hero.title);
    const hidden = await page.evaluate(
      () =>
        [...document.querySelectorAll("[data-revele]")].filter(
          (element) => getComputedStyle(element).opacity !== "1",
        ).length,
    );
    expect(hidden).toBe(0);
    for (const item of texte.features.items) {
      await expect(page.getByRole("heading", { name: item.title, exact: true })).toBeVisible();
    }
    await expect(page.getByText(texte.faq.items[0].question)).toBeVisible();
    // La mini-caisse est du CSS seul : elle joue sans script et finit complète.
    await expect(page.locator("[data-caisse-etape=encaisse]")).toHaveCSS("opacity", "1", {
      timeout: 10_000,
    });
  });
});
