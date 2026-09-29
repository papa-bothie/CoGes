import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const DEMO = {
  slug: process.env.E2E_COMPANY_SLUG ?? "demo",
  email: process.env.E2E_EMAIL ?? "gerant@demo.example.com",
  password: process.env.E2E_PASSWORD ?? "demo-coges-2026",
};

export async function loginThroughUi(
  page: Page,
  credentials: { slug: string; email: string; password: string },
) {
  await page.getByLabel("Identifiant d'entreprise").fill(credentials.slug);
  await page.getByLabel("Adresse e-mail").fill(credentials.email);
  await page.getByLabel("Mot de passe").fill(credentials.password);
  await page.getByRole("button", { name: "Se connecter" }).click();
}

/** Jeton d'un gérant, obtenu par l'API **à travers la réécriture du front**. */
export async function managerToken(request: APIRequestContext): Promise<string> {
  const response = await request.post("/api/v1/auth/login", {
    data: { company_slug: DEMO.slug, email: DEMO.email, password: DEMO.password },
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).access_token as string;
}

/** Crée un vendeur par les routes réelles et renvoie ses identifiants. */
export async function createSalesperson(request: APIRequestContext) {
  const token = await managerToken(request);
  const headers = { Authorization: `Bearer ${token}` };
  const roles = await (await request.get("/api/v1/roles?page_size=50", { headers })).json();
  const role = roles.items.find((item: { name: string }) => item.name === "vendeur");
  const email = `vendeur-e2e-${Date.now()}@${DEMO.slug}.example.com`;
  const password = "vendeur-e2e-2026";
  const created = await request.post("/api/v1/users", {
    headers,
    data: { email, full_name: "Vendeur E2E", password, role_ids: [role.id] },
  });
  expect(created.status()).toBe(201);
  return { slug: DEMO.slug, email, password };
}

/** Appels directs à l'API (à travers la réécriture du front), pour préparer un parcours. */
export async function managerApi(request: APIRequestContext) {
  const token = await managerToken(request);
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
