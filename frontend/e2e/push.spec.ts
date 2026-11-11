import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page, type Worker } from "@playwright/test";

import { E2E, loginThroughUi, managerApi } from "./fixtures";

/**
 * Notifications sur le téléphone (prompt 36, bloc N, ADR 0120), sur un build de production
 * sous Chromium : « Activer » demande la permission (accordée ici), l'abonnement part au
 * serveur, un push livré par le navigateur (protocole DevTools) s'affiche avec le texte du
 * serveur, et le toucher ouvre l'écran nommé.
 *
 * L'abonnement du navigateur est simulé (`PushManager.subscribe`) : un Chromium de test ne
 * joint pas le service de push de Google. L'adresse reste celle d'un service connu, que le
 * serveur exige.
 */
test.describe.configure({ timeout: 120_000, mode: "serial" });
// Le Chromium complet (nouveau mode sans fenêtre) : `chromium-headless-shell`, celui de
// Playwright par défaut, répond toujours « refusé » aux notifications.
test.use({ channel: "chromium" });

const ENDPOINT = `https://fcm.googleapis.com/fcm/send/e2e-${Date.now()}`;

async function fakeSubscription(context: BrowserContext) {
  await context.addInitScript((endpoint) => {
    const key = (bytes: Uint8Array) =>
      btoa(String.fromCharCode(...bytes))
        .replace(/\+/g, "-")
        .replace(/\//g, "_")
        .replace(/=+$/, "");
    const publicKey = new Uint8Array(65);
    publicKey[0] = 4;
    crypto.getRandomValues(publicKey.subarray(1));
    const auth = crypto.getRandomValues(new Uint8Array(16));
    // Gardé le temps de l'onglet, comme un vrai abonnement survit à un rechargement.
    const FLAG = "e2e-push-subscribed";
    const subscription = {
      endpoint,
      toJSON: () => ({ endpoint, keys: { p256dh: key(publicKey), auth: key(auth) } }),
      unsubscribe: async () => {
        sessionStorage.removeItem(FLAG);
        return true;
      },
    } as unknown as PushSubscription;
    PushManager.prototype.subscribe = async () => {
      sessionStorage.setItem(FLAG, "1");
      return subscription;
    };
    PushManager.prototype.getSubscription = async () =>
      sessionStorage.getItem(FLAG) ? subscription : null;
  }, ENDPOINT);
}

async function controlled(page: Page) {
  await page.waitForFunction(() => navigator.serviceWorker.ready.then(() => true));
  if (!(await page.evaluate(() => Boolean(navigator.serviceWorker.controller)))) {
    await page.reload();
  }
  await expect
    .poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller)))
    .toBe(true);
}

async function deliverPush(page: Page, message: Record<string, string>) {
  const cdp = await page.context().newCDPSession(page);
  const registration = new Promise<string>((resolve) =>
    cdp.on("ServiceWorker.workerRegistrationUpdated", ({ registrations }) => {
      const found = registrations.find((item) => !item.isDeleted);
      if (found) resolve(found.registrationId);
    }),
  );
  await cdp.send("ServiceWorker.enable");
  await cdp.send("ServiceWorker.deliverPushMessage", {
    origin: new URL(page.url()).origin,
    registrationId: await registration,
    data: JSON.stringify(message),
  });
}

/** Ce que le parcours lit du worker : le projet n'embarque pas les types WebWorker. */
type ShownNotification = { title: string; data: unknown };
type WorkerScope = {
  registration: { getNotifications: () => Promise<ShownNotification[]> };
  dispatchEvent: (event: Event) => boolean;
};
type NotificationEventCtor = new (type: string, init: { notification: ShownNotification }) => Event;

function worker(context: BrowserContext): Worker {
  const [found] = context.serviceWorkers();
  if (!found) throw new Error("Aucun service worker");
  return found;
}

test("activer, recevoir une alerte sans montant, la toucher ouvre le bon écran", async ({
  page,
  context,
  request,
}) => {
  await context.grantPermissions(["notifications"]);
  await fakeSubscription(context);
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  await controlled(page);

  // Le menu du compte propose l'écran, puisque le serveur a ses clés.
  await page.getByRole("button", { name: /Réglages et compte/ }).click();
  await page.getByRole("menuitem", { name: "Notifications sur le téléphone" }).click();
  await expect(page.getByRole("heading", { name: "Notifications sur le téléphone" })).toBeVisible();
  await page.getByRole("button", { name: "Activer les notifications" }).click();
  await expect(page.getByText("Les notifications sont activées sur cet appareil.")).toBeVisible();

  const client = await managerApi(request);
  const devices = (await client.get("/notifications/push/subscriptions")).items as unknown[];
  expect(devices.length).toBeGreaterThanOrEqual(1);

  // Un push arrive, tel que le worker l'écrit (texte sans montant, chemin relatif).
  await deliverPush(page, {
    title: "Riz 25 kg est épuisé",
    body: "Vous ne pouvez plus en vendre.",
    url: "/sales",
    tag: "coges-alertes",
  });
  const sw = worker(context);
  await expect
    .poll(() =>
      sw.evaluate(() =>
        (self as unknown as WorkerScope).registration
          .getNotifications()
          .then((items) => items.map((item) => ({ title: item.title, data: item.data }))),
      ),
    )
    .toEqual([{ title: "Riz 25 kg est épuisé", data: { url: "/sales" } }]);

  // Le toucher : l'onglet ouvert va sur l'écran nommé.
  await sw.evaluate(async () => {
    const scope = self as unknown as WorkerScope;
    const Click = (self as unknown as { NotificationEvent: NotificationEventCtor })
      .NotificationEvent;
    const [notification] = await scope.registration.getNotifications();
    try {
      scope.dispatchEvent(new Click("notificationclick", { notification: notification! }));
    } catch {
      // `waitUntil` refuse un événement simulé ; la navigation, elle, est lancée.
    }
  });
  await expect(page).toHaveURL(/\/sales$/, { timeout: 15_000 });

  // L'écran, sur téléphone : rien ne déborde, axe sans violation.
  await page.setViewportSize({ width: 360, height: 760 });
  await page.goto("/account/notifications");
  await expect(page.getByRole("button", { name: "Désactiver sur cet appareil" })).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    )
    .toBeLessThanOrEqual(0);
  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(axe.violations).toEqual([]);

  // « Désactiver » : l'abonnement s'arrête au serveur.
  await page.getByRole("button", { name: "Désactiver sur cet appareil" }).click();
  await expect(
    page.getByText("Les notifications sont désactivées sur cet appareil."),
  ).toBeVisible();
});
