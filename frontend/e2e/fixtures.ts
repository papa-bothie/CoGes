import { expect, type APIRequestContext, type Page } from "@playwright/test";

export type Credentials = { slug: string; email: string; password: string };

/** La boutique de démonstration : lue par les captures, l'audit axe et les écrans de pilotage. */
export const DEMO: Credentials = {
  slug: process.env.E2E_COMPANY_SLUG ?? "demo",
  email: process.env.E2E_EMAIL ?? "gerant@demo.example.com",
  password: process.env.E2E_PASSWORD ?? "demo-coges-2026",
};

/**
 * L'entreprise des parcours qui écrivent (ADR 0060) : articles, clients et vendeurs
 * « E2E » n'y côtoient jamais la démo. Créée vide par `make e2e-reset`.
 */
export const E2E: Credentials = {
  slug: process.env.E2E_WRITE_SLUG ?? "e2e",
  email: process.env.E2E_WRITE_EMAIL ?? "gerant@e2e.example.com",
  password: process.env.E2E_PASSWORD ?? "demo-coges-2026",
};

export async function loginThroughUi(page: Page, credentials: Credentials) {
  await page.getByLabel("Code de la boutique").fill(credentials.slug);
  await page.getByLabel("Votre e-mail ou téléphone").fill(credentials.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "Entrer" }).click();
}

/** Jeton d'un gérant, obtenu par l'API **à travers la réécriture du front**. */
export async function managerToken(
  request: APIRequestContext,
  company: Credentials = E2E,
): Promise<string> {
  const response = await request.post("/api/v1/auth/login", {
    data: { company_slug: company.slug, email: company.email, password: company.password },
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).access_token as string;
}

/**
 * Vide les brouillons du gérant : « Nouvelle vente » reprend le brouillon du jour de la même
 * personne (ADR 0070), et chaque parcours doit partir d'un panier vide. Un brouillon ne se
 * supprime pas ; ses lignes, si.
 */
export async function emptyMyDrafts(request: APIRequestContext, company: Credentials = E2E) {
  const token = await managerToken(request, company);
  const headers = { Authorization: `Bearer ${token}` };
  const drafts = await request.get("/api/v1/sales?status=draft&mine=true&page_size=100", {
    headers,
  });
  for (const draft of (await drafts.json()).items as { id: string }[]) {
    const detail = await request.get(`/api/v1/sales/${draft.id}`, { headers });
    for (const item of (await detail.json()).items as { id: string }[]) {
      const removed = await request.delete(`/api/v1/sales/${draft.id}/items/${item.id}`, {
        headers,
      });
      expect(removed.ok()).toBeTruthy();
    }
  }
}

/** Crée un vendeur par les routes réelles et renvoie ses identifiants. */
export async function createSalesperson(request: APIRequestContext, company: Credentials = E2E) {
  const token = await managerToken(request, company);
  const headers = { Authorization: `Bearer ${token}` };
  const roles = await (await request.get("/api/v1/roles?page_size=50", { headers })).json();
  const role = roles.items.find((item: { name: string }) => item.name === "vendeur");
  const email = `vendeur-e2e-${Date.now()}@${company.slug}.example.com`;
  const password = "vendeur-e2e-2026";
  const created = await request.post("/api/v1/users", {
    headers,
    data: { email, full_name: "Vendeur E2E", password, role_ids: [role.id] },
  });
  expect(created.status()).toBe(201);
  return { slug: company.slug, email, password };
}

/** Appels directs à l'API (à travers la réécriture du front), pour préparer un parcours. */
export async function managerApi(request: APIRequestContext, company: Credentials = E2E) {
  const token = await managerToken(request, company);
  const headers = { Authorization: `Bearer ${token}` };
  const write = () => ({ ...headers, "Idempotency-Key": crypto.randomUUID() });
  const call = async (method: "get" | "post" | "patch", path: string, data?: unknown) => {
    const response = await request[method](`/api/v1${path}`, {
      headers: method === "get" ? headers : write(),
      data,
    });
    expect(response.ok(), `${method.toUpperCase()} ${path} → ${response.status()}`).toBeTruthy();
    return response.status() === 204 ? null : await response.json();
  };
  return {
    get: (path: string) => call("get", path),
    post: (path: string, data: unknown) => call("post", path, data),
    patch: (path: string, data: unknown) => call("patch", path, data),
  };
}

export type ManagerApi = Awaited<ReturnType<typeof managerApi>>;

/** Un article neuf au prix donné, sans taxe, avec `stock` unités au coût de 600. */
export async function stockedProduct(
  client: ManagerApi,
  { stock, price = "1000" }: { stock: string; price?: string },
) {
  const marker = crypto.randomUUID().slice(0, 8);
  const product = await client.post("/products", {
    sku: `E2E-${marker}`,
    name: `Article E2E ${marker}`,
    unit_price: price,
    default_tax_rate: "0",
    reorder_point: "1",
  });
  await client.post("/inventory/movements", {
    product_id: product.id,
    type: "initial",
    qty_delta: stock,
    unit_cost: "600",
  });
  return product as { id: string; name: string; sku: string };
}

export async function customerWithCredit(client: ManagerApi) {
  const marker = crypto.randomUUID().slice(0, 8);
  return (await client.post("/customers", {
    name: `Client E2E ${marker}`,
    credit_limit: "1000000",
  })) as { id: string; name: string };
}
