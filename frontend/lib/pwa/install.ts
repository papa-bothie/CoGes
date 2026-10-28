/**
 * Installation de l'application (ADR 0102). Android et Chrome : l'événement
 * `beforeinstallprompt` est gardé, puis rejoué par « Installer l'application ». iPhone (Safari
 * n'a pas cet événement) : une courte aide. Une fois installée, plus aucune invitation.
 */

type InstallPrompt = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

export type InstallState = {
  /** Android / Chrome : l'invite du navigateur est prête. */
  canPrompt: boolean;
  /** iPhone / iPad dans Safari, pas encore installée : l'aide « Partager ». */
  iosHelp: boolean;
  installed: boolean;
};

const VISITS = "coges:pwa:visits";
const COUNTED = "coges:pwa:counted";
const DISMISSED = "coges:pwa:invite-dismissed";
/** L'invitation vient à la troisième ouverture de l'application, jamais avant. */
export const INVITE_AFTER_VISITS = 3;

let deferred: InstallPrompt | null = null;
let state: InstallState = { canPrompt: false, iosHelp: false, installed: false };
const listeners = new Set<() => void>();

function emit(next: Partial<InstallState>): void {
  state = { ...state, ...next };
  listeners.forEach((listener) => listener());
}

function standalone(): boolean {
  return (
    window.matchMedia?.("(display-mode: standalone)").matches === true ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

function read(storage: () => Storage, key: string): string | null {
  try {
    return storage().getItem(key);
  } catch {
    return null;
  }
}

function write(storage: () => Storage, key: string, value: string): void {
  try {
    storage().setItem(key, value);
  } catch {
    // Sans stockage, l'invitation ne revient simplement pas compter.
  }
}

export function subscribeInstall(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function installState(): InstallState {
  return state;
}

export const SERVER_INSTALL_STATE: InstallState = {
  canPrompt: false,
  iosHelp: false,
  installed: false,
};

/** À appeler une fois au chargement : capture l'invite et compte les ouvertures. */
export function watchInstall(): () => void {
  const installed = standalone();
  const ios = /iPhone|iPad|iPod/i.test(navigator.userAgent) && !installed;
  emit({ installed, iosHelp: ios });
  if (!read(() => window.sessionStorage, COUNTED)) {
    write(() => window.sessionStorage, COUNTED, "1");
    const visits = Number(read(() => window.localStorage, VISITS) ?? "0") + 1;
    write(() => window.localStorage, VISITS, String(visits));
  }
  const onPrompt = (event: Event) => {
    event.preventDefault();
    deferred = event as InstallPrompt;
    emit({ canPrompt: true });
  };
  const onInstalled = () => {
    deferred = null;
    emit({ canPrompt: false, iosHelp: false, installed: true });
  };
  window.addEventListener("beforeinstallprompt", onPrompt);
  window.addEventListener("appinstalled", onInstalled);
  return () => {
    window.removeEventListener("beforeinstallprompt", onPrompt);
    window.removeEventListener("appinstalled", onInstalled);
  };
}

export async function promptInstall(): Promise<void> {
  if (!deferred) return;
  const event = deferred;
  deferred = null;
  emit({ canPrompt: false });
  await event.prompt();
  const choice = await event.userChoice.catch(() => ({ outcome: "dismissed" as const }));
  if (choice.outcome === "accepted") emit({ installed: true });
  dismissInvite();
}

/** L'invitation ne revient pas : la personne a dit non, ou l'a installée. */
export function dismissInvite(): void {
  write(() => window.localStorage, DISMISSED, "1");
  emit({});
}

/** L'invitation discrète : une fois, après quelques ouvertures, jamais sur la connexion. */
export function shouldInvite(current: InstallState, pathname: string): boolean {
  if (current.installed || (!current.canPrompt && !current.iosHelp)) return false;
  if (pathname.startsWith("/login") || /^\/sales\/(new|[^/]+\/edit)/.test(pathname)) return false;
  if (read(() => window.localStorage, DISMISSED)) return false;
  return Number(read(() => window.localStorage, VISITS) ?? "0") >= INVITE_AFTER_VISITS;
}
