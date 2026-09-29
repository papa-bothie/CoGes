"use client";

import type { ReactNode } from "react";

import { can, type PermissionRule } from "@/lib/permissions";

import { useMe } from "./use-me";

/** Confort d'affichage : le serveur revérifie chaque droit. */
export function usePermission(rule: PermissionRule): boolean {
  const { data } = useMe();
  return can(data?.permissions, rule);
}

/** Affiche `children` si la permission est détenue, sinon `fallback` (rien par défaut). */
export function Can({
  permission,
  children,
  fallback = null,
}: {
  permission: PermissionRule;
  children: ReactNode;
  fallback?: ReactNode;
}) {
  return usePermission(permission) ? children : fallback;
}
