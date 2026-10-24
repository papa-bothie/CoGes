/**
 * État d'une liste dans l'adresse (prompt 27, D4 b) : un lien se partage et rouvre la
 * même vue. Les valeurs vides disparaissent de l'adresse ; changer un filtre ramène à la
 * page 1.
 */
export function withParams(
  pathname: string,
  current: URLSearchParams,
  changes: Record<string, string | null | undefined>,
): string {
  const next = new URLSearchParams(current.toString());
  for (const [key, value] of Object.entries(changes)) {
    if (value === null || value === undefined || value === "") next.delete(key);
    else next.set(key, value);
  }
  if (!("page" in changes)) next.delete("page");
  const query = next.toString();
  return query ? `${pathname}?${query}` : pathname;
}

export function pageOf(params: URLSearchParams): number {
  const page = Number(params.get("page") ?? "1");
  return Number.isInteger(page) && page >= 1 ? page : 1;
}
