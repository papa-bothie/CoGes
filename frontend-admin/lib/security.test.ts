import { describe, expect, it } from "vitest";

import type { SecurityEvent } from "@/lib/api/schema";

import { securityEventText, securityEventTone } from "./security";

const base: SecurityEvent = {
  kind: "new_device",
  platform_user_id: "u1",
  display_name: "Awa Diallo",
  device: "Firefox · Windows",
  occurred_at: "2026-10-30T09:15:00Z",
};

describe("signaux de sécurité", () => {
  it("nomme la personne, le navigateur et le moment", () => {
    expect(securityEventText(base)).toMatch(
      /^Awa Diallo s'est connecté depuis un nouvel appareil \(Firefox · Windows\) le 30\/10\/2026/,
    );
    expect(securityEventTone(base)).toBe("attention");
  });

  it("un code de secours utilisé et une réinitialisation sont en rouge", () => {
    for (const kind of ["recovery_code_used", "mfa_reset"] as const) {
      expect(securityEventTone({ ...base, kind })).toBe("danger");
    }
    expect(securityEventText({ ...base, kind: "recovery_code_used" })).toContain(
      "a utilisé un code de secours",
    );
    expect(securityEventText({ ...base, kind: "mfa_reset", device: null })).toContain(
      "a été réinitialisée",
    );
  });
});
