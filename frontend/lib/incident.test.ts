import { describe, expect, it } from "vitest";

import { incidentReference } from "@/lib/incident";

describe("référence d'incident", () => {
  it("garde 8 signes, en majuscules, par deux groupes", () => {
    expect(incidentReference("ab12cd34-5678-90ef-aa00-123456789abc")).toBe("AB12 CD34");
  });

  it("ne montre rien sans identifiant exploitable", () => {
    expect(incidentReference(null)).toBeNull();
    expect(incidentReference("")).toBeNull();
    expect(incidentReference("abc")).toBeNull();
  });
});
