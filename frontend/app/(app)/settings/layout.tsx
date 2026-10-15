import type { ReactNode } from "react";

import { SettingsFrame } from "./settings-frame";

/** Réglages, maquette v2 (écran 24) : le menu des rubriques à gauche, la rubrique à droite. */
export default function SettingsLayout({ children }: { children: ReactNode }) {
  return <SettingsFrame>{children}</SettingsFrame>;
}
