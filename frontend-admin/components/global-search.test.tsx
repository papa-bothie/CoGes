import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GlobalSearch, SEARCH_DELAY_MS, type SearchHit } from "./global-search";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const HITS: SearchHit[] = [
  { key: "c1", label: "Boutique Awa", detail: "awa", kind: "Entreprise", href: "/companies/c1" },
  { key: "t1", label: "Moussa Badji", detail: "m@x", kind: "Équipe", href: "/team?member=t1" },
];

describe("recherche globale", () => {
  it("« / » y met le curseur, la saisie attend 300 ms, Entrée ouvre le premier résultat", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const search = vi.fn(async () => HITS);
    render(
      <>
        <p>Une page</p>
        <GlobalSearch search={search} />
      </>,
    );
    await user.keyboard("/");
    const input = screen.getByRole("combobox", { name: "Rechercher une entreprise ou un compte" });
    expect(input).toHaveFocus();
    await user.keyboard("awa");
    expect(search).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(SEARCH_DELAY_MS);
    });
    expect(search).toHaveBeenCalledWith("awa");
    expect(await screen.findByRole("option", { name: /Boutique Awa/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await user.keyboard("{ArrowDown}{Enter}");
    expect(push).toHaveBeenCalledWith("/team?member=t1");
    vi.useRealTimers();
  });

  it("« / » tapé dans un champ reste un caractère", async () => {
    render(
      <>
        <label>
          Note <input />
        </label>
        <GlobalSearch search={async () => []} />
      </>,
    );
    const note = screen.getByLabelText("Note");
    await userEvent.type(note, "a/b");
    expect(note).toHaveValue("a/b");
  });
});
