import { describe, expect, it } from "vitest";

import { amountInWords, numberInWords } from "./number-words";

describe("numberInWords", () => {
  it("écrit les nombres en français (orthographe traditionnelle)", () => {
    const cases: [bigint, string][] = [
      [0n, "zéro"],
      [1n, "un"],
      [16n, "seize"],
      [17n, "dix-sept"],
      [21n, "vingt et un"],
      [71n, "soixante et onze"],
      [80n, "quatre-vingts"],
      [81n, "quatre-vingt-un"],
      [91n, "quatre-vingt-onze"],
      [100n, "cent"],
      [200n, "deux cents"],
      [201n, "deux cent un"],
      [1000n, "mille"],
      [2000n, "deux mille"],
      [25000n, "vingt-cinq mille"],
      [80000n, "quatre-vingt mille"],
      [200000n, "deux cent mille"],
      [1000000n, "un million"],
      [2500000n, "deux millions cinq cent mille"],
      [1001000000n, "un milliard un million"],
    ];
    for (const [value, words] of cases) expect(numberInWords(value)).toBe(words);
  });

  it("écrit un montant en francs CFA, sans décimales", () => {
    expect(amountInWords("25000.00")).toBe("vingt-cinq mille francs CFA");
    expect(amountInWords("1.00")).toBe("un franc CFA");
  });
});
