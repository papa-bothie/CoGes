/** Clé du réglage de densité dans `localStorage` (voir `lib/density.ts`). */
export const DENSITY_KEY = "coges-density";

/** Script injecté dans `<head>` : évite un changement de densité visible au chargement. */
export const DENSITY_BOOT_SCRIPT = `try{if(localStorage.getItem("${DENSITY_KEY}")==="comfortable")document.documentElement.dataset.density="comfortable"}catch(e){}`;
