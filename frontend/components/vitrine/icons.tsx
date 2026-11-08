import {
  Boxes,
  Download,
  HandCoins,
  LayoutDashboard,
  Package,
  ScanBarcode,
  ShoppingCart,
  Smartphone,
  Smile,
  TrendingUp,
  UserCheck,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

import type { IconName, Rubrique } from "@/content/vitrine-texte";

export const ICONS: Record<IconName, LucideIcon> = {
  "shopping-cart": ShoppingCart,
  package: Package,
  wallet: Wallet,
  "layout-dashboard": LayoutDashboard,
  "scan-barcode": ScanBarcode,
  users: Users,
  "hand-coins": HandCoins,
  boxes: Boxes,
  "trending-up": TrendingUp,
  "user-check": UserCheck,
  smile: Smile,
  smartphone: Smartphone,
  download: Download,
};

/** Classes complètes (Tailwind ne lit que des noms entiers) : pastille pleine et teinte. */
export const RUBRIQUE: Record<Rubrique, { solid: string; tint: string; ink: string }> = {
  ventes: { solid: "bg-ventes", tint: "bg-ventes-teinte", ink: "text-ventes-encre" },
  stock: { solid: "bg-stock", tint: "bg-stock-teinte", ink: "text-stock-encre" },
  argent: { solid: "bg-argent", tint: "bg-argent-teinte", ink: "text-argent-encre" },
  clients: { solid: "bg-clients", tint: "bg-clients-teinte", ink: "text-clients-encre" },
  conseils: { solid: "bg-conseils", tint: "bg-conseils-teinte", ink: "text-conseils-encre" },
  depenses: { solid: "bg-depenses", tint: "bg-depenses-teinte", ink: "text-depenses-encre" },
};
