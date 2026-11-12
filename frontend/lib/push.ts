/**
 * Notifications sur le téléphone, côté navigateur (Web Push, ADR 0120).
 *
 * La permission du navigateur n'est demandée **qu'après** l'appui sur « Activer les
 * notifications » (`enablePush`), jamais au chargement d'une page. L'abonnement rendu par le
 * navigateur part au serveur, qui chiffre ensuite chaque alerte pour cet appareil seul.
 *
 * Sur iPhone et iPad, Safari ne reçoit de notifications que si CoGes est installé sur
 * l'écran d'accueil (iOS 16.4 et plus) : `pushState` le dit, l'écran montre l'aide
 * d'installation (ADR 0102).
 *
 * Sans dépendance au client d'API : la déconnexion (`lib/auth/session.ts`) l'appelle avec
 * son propre jeton, avant d'oublier la session.
 */

export type PushState =
  /** Le serveur n'a pas de clés : rien à proposer. */
  | "unavailable"
  /** Ce navigateur ne sait pas recevoir de notifications. */
  | "unsupported"
  /** iPhone ou iPad, CoGes ouvert dans Safari : l'installer d'abord. */
  | "needs-install"
  /** L'utilisateur a refusé : à réautoriser dans les réglages du navigateur. */
  | "denied"
  | "off"
  | "on";

const PUSH = "/api/v1/notifications/push";

export function isAppleMobile(userAgent: string, maxTouchPoints: number): boolean {
  // iPadOS se présente comme un Mac ; il se trahit par l'écran tactile.
  return /iPhone|iPad|iPod/.test(userAgent) || (/Macintosh/.test(userAgent) && maxTouchPoints > 1);
}

export function isInstalled(): boolean {
  const standalone = (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return standalone || window.matchMedia?.("(display-mode: standalone)").matches === true;
}

function supported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

/** Clé publique VAPID (base64url) → octets, pour `applicationServerKey`. */
export function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = base64url
    .replace(/-/g, "+")
    .replace(/_/g, "/")
    .padEnd(Math.ceil(base64url.length / 4) * 4, "=");
  const raw = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index);
  return bytes;
}

async function currentSubscription(): Promise<PushSubscription | null> {
  if (!supported()) return null;
  const registration = await navigator.serviceWorker.getRegistration();
  return (await registration?.pushManager.getSubscription()) ?? null;
}

/** Où en est cet appareil, sans rien demander à personne. */
export async function pushState(publicKey: string | null): Promise<PushState> {
  if (!publicKey) return "unavailable";
  if (isAppleMobile(navigator.userAgent, navigator.maxTouchPoints ?? 0) && !isInstalled()) {
    return "needs-install";
  }
  if (!supported()) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  const subscription = await currentSubscription();
  return subscription && Notification.permission === "granted" ? "on" : "off";
}

/** « Mon téléphone (Android) » : de quoi reconnaître l'appareil dans la liste. */
export function deviceLabel(userAgent: string, maxTouchPoints: number): string {
  if (isAppleMobile(userAgent, maxTouchPoints)) {
    return /iPad/.test(userAgent) || /Macintosh/.test(userAgent) ? "iPad" : "iPhone";
  }
  if (/Android/.test(userAgent)) return "Téléphone Android";
  if (/Windows/.test(userAgent)) return "Ordinateur Windows";
  if (/Macintosh/.test(userAgent)) return "Mac";
  if (/Linux/.test(userAgent)) return "Ordinateur Linux";
  return "Navigateur";
}

export type SendSubscription = (body: {
  endpoint: string;
  keys: { p256dh: string; auth: string };
  device_label: string;
}) => Promise<unknown>;

/**
 * Appui sur « Activer » : permission du navigateur, puis abonnement, puis serveur. Rend
 * l'état obtenu ; un refus du navigateur rend `denied`, jamais une erreur.
 */
export async function enablePush(publicKey: string, send: SendSubscription): Promise<PushState> {
  if (!supported()) return "unsupported";
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return permission === "denied" ? "denied" : "off";
  const registration = await navigator.serviceWorker.ready;
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes(publicKey),
    }));
  const json = subscription.toJSON();
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
    throw new Error("Abonnement incomplet");
  }
  try {
    await send({
      endpoint: json.endpoint,
      keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
      device_label: deviceLabel(navigator.userAgent, navigator.maxTouchPoints ?? 0),
    });
  } catch (error) {
    // Refusé par le serveur : rien ne reste abonné côté navigateur.
    await subscription.unsubscribe().catch(() => undefined);
    throw error;
  }
  return "on";
}

/** « Désactiver », ou la déconnexion : le serveur d'abord, puis le navigateur. */
export async function disablePush(remove: (endpoint: string) => Promise<unknown>): Promise<void> {
  const subscription = await currentSubscription().catch(() => null);
  if (!subscription) return;
  try {
    await remove(subscription.endpoint);
  } finally {
    await subscription.unsubscribe().catch(() => undefined);
  }
}

/**
 * À la déconnexion (`lib/auth/session.ts`) : l'abonnement de cet appareil est arrêté au
 * serveur, avec le jeton encore valide, puis retiré du navigateur. Jamais bloquant.
 */
export async function stopPushAtLogout(token: string | null): Promise<void> {
  if (!supported()) return;
  await disablePush(async (endpoint) => {
    if (!token) return;
    await fetch(`${PUSH}/subscriptions/remove?logout=true`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ endpoint }),
    });
  }).catch(() => undefined);
}
