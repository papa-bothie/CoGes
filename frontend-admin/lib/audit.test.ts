import { describe, expect, it } from "vitest";

import type { AuditEntry } from "@/lib/api/schema";

import { describeEntry } from "./audit";

function entry(partial: Partial<AuditEntry>): AuditEntry {
  return {
    id: 1,
    occurred_at: "2026-10-24T10:00:00Z",
    actor_id: "a",
    actor_name: "Aïssatou Diop",
    action: "update",
    entity_table: "platform_users",
    entity_id: "m",
    entity_name: "Moussa Badji",
    target_company_id: null,
    target_company_name: null,
    diff: {},
    ...partial,
  };
}

describe("le journal en phrases", () => {
  it("un changement de profil", () => {
    expect(
      describeEntry(
        entry({ diff: { before: { role: "support" }, after: { role: "administrator" } } }),
      ),
    ).toBe("Aïssatou D. a passé Moussa B. de Support à Administrateur");
  });

  it("une suspension, avec sa raison", () => {
    expect(
      describeEntry(
        entry({
          diff: { before: { is_active: true }, after: { is_active: false }, reason: "Départ" },
        }),
      ),
    ).toBe("Aïssatou D. a suspendu Moussa B. — « Départ »");
  });

  it("une invitation, une entreprise suspendue, un paiement, une tâche automatique", () => {
    expect(
      describeEntry(
        entry({
          action: "insert",
          entity_table: "platform_invitations",
          diff: { after: { email: "m@x.example.com", role: "support" } },
        }),
      ),
    ).toBe("Aïssatou D. a invité Moussa B. (m@x.example.com) comme Support");
    expect(
      describeEntry(
        entry({
          entity_table: "companies",
          target_company_name: "Boutique Awa",
          diff: { before: { status: "active" }, after: { status: "suspended" }, reason: "Impayé" },
        }),
      ),
    ).toBe("Aïssatou D. a suspendu Boutique Awa — « Impayé »");
    expect(
      describeEntry(
        entry({
          action: "insert",
          entity_table: "subscription_payments",
          target_company_name: "Boutique Awa",
          diff: { after: { amount_fcfa: "9900.00", method: "wave" } },
        }),
      ),
    ).toBe("Aïssatou D. a enregistré un paiement de 9 900 FCFA (Wave) pour Boutique Awa");
    expect(
      describeEntry(
        entry({
          actor_id: null,
          actor_name: null,
          entity_table: "subscriptions",
          target_company_name: "Boutique Awa",
          diff: { before: { status: "trial" }, after: { status: "suspended" } },
        }),
      ),
    ).toBe("CoGes (automatique) a mis l'abonnement de Boutique Awa en « Suspendu »");
  });

  it("la double authentification, sans aucun secret (ADR 0105)", () => {
    expect(
      describeEntry(
        entry({
          action: "login",
          entity_id: "a",
          diff: { method: "recovery_code", new_device: true, device: "Firefox · Linux" },
        }),
      ),
    ).toBe(
      "Aïssatou D. s'est connecté avec un code de secours depuis un nouvel appareil (Firefox · Linux)",
    );
    expect(describeEntry(entry({ action: "login", diff: { method: "totp" } }))).toBe(
      "Aïssatou D. s'est connecté",
    );
    expect(describeEntry(entry({ diff: { mfa: "enabled", device: "Edge · Windows" } }))).toBe(
      "Moussa B. a activé sa double authentification",
    );
    expect(describeEntry(entry({ diff: { mfa: "reset", reason: "Téléphone perdu" } }))).toBe(
      "Aïssatou D. a réinitialisé la double authentification de Moussa B. — « Téléphone perdu »",
    );
    expect(
      describeEntry(entry({ actor_id: null, diff: { mfa: "reset", reason: "commande" } })),
    ).toBe(
      "La double authentification de Moussa B. a été réinitialisée en ligne de commande — « commande »",
    );
  });

  it("jamais de JSON brut, même pour un cas inconnu", () => {
    const text = describeEntry(entry({ entity_table: "autre", diff: { x: 1 } }));
    expect(text).not.toContain("{");
  });
});
