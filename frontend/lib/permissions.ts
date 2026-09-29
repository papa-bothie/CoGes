/**
 * Garde de permissions **d'affichage**. Elle masque ou désactive ce que le serveur
 * refuserait ; elle n'autorise jamais rien. Chaque route de l'API revérifie le droit
 * (`require_permission`), et c'est sa réponse qui fait foi.
 *
 * Les codes suivent le catalogue du backend : `ressource:action` (ADR 0007).
 */

export type PermissionCode = `${string}:${string}`;

export type PermissionRule = PermissionCode | { anyOf: readonly PermissionCode[] };

export function can(
  permissions: readonly string[] | undefined,
  rule: PermissionRule | undefined,
): boolean {
  if (rule === undefined) return true;
  if (!permissions) return false;
  if (typeof rule === "string") return permissions.includes(rule);
  return rule.anyOf.some((code) => permissions.includes(code));
}

export function filterByPermission<T extends { permission?: PermissionRule }>(
  items: readonly T[],
  permissions: readonly string[] | undefined,
): T[] {
  return items.filter((item) => can(permissions, item.permission));
}
