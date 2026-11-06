import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { saveBlob } from "@/lib/files";
import { labels } from "@/lib/labels";
import { pdfFromResponse, sharePdf } from "@/lib/pdf-share";
import { renderWithClient } from "@/test/render";

import { PdfActions } from "./pdf-actions";

const t = labels.receipt.pdf;

vi.mock("@/lib/files", async (original) => ({
  ...(await original<typeof import("@/lib/files")>()),
  saveBlob: vi.fn(),
}));

const PDF = {
  blob: new Blob(["%PDF-1.4"], { type: "application/pdf" }),
  filename: "Facture-1044-Boutique.pdf",
};

function stubShare(supported: boolean, share = vi.fn(async () => undefined)) {
  Object.defineProperty(navigator, "share", {
    configurable: true,
    value: supported ? share : undefined,
  });
  Object.defineProperty(navigator, "canShare", {
    configurable: true,
    value: supported ? () => true : undefined,
  });
  return share;
}

beforeEach(() => {
  vi.mocked(saveBlob).mockClear();
});
afterEach(() => {
  stubShare(false);
});

describe("pdfFromResponse", () => {
  it("garde le nom du serveur", async () => {
    const response = new Response(null, {
      headers: {
        "Content-Disposition":
          "attachment; filename=\"Facture-1044-Boutique.pdf\"; filename*=UTF-8''Facture-1044-Boutique.pdf",
      },
    });
    const pdf = await pdfFromResponse({ data: PDF.blob, response }, "Recu.pdf");
    expect(pdf.filename).toBe("Facture-1044-Boutique.pdf");
  });

  it("une erreur de l'API devient une erreur lisible", async () => {
    const response = new Response(null, { status: 404 });
    await expect(
      pdfFromResponse(
        { error: { error: { code: "not_found", message: "Introuvable." } }, response },
        "x.pdf",
      ),
    ).rejects.toThrow();
  });
});

describe("sharePdf (prompt 35, bloc T)", () => {
  it("partage le fichier quand le téléphone le permet", async () => {
    const share = stubShare(true);
    expect(await sharePdf(PDF, { title: "Reçu", text: "Merci" })).toBe("shared");
    const [payload] = share.mock.calls[0] as unknown as [ShareData];
    expect(payload.files?.[0]?.name).toBe("Facture-1044-Boutique.pdf");
    expect(payload.files?.[0]?.type).toBe("application/pdf");
    expect(saveBlob).not.toHaveBeenCalled();
  });

  it("sans partage de fichier, le PDF est téléchargé", async () => {
    stubShare(false);
    expect(await sharePdf(PDF, { title: "Reçu" })).toBe("downloaded");
    expect(saveBlob).toHaveBeenCalledWith(PDF.blob, PDF.filename);
  });

  it("un partage annulé n'est ni une erreur ni un téléchargement", async () => {
    stubShare(
      true,
      vi.fn(async () => {
        throw new DOMException("annulé", "AbortError");
      }),
    );
    expect(await sharePdf(PDF, { title: "Reçu" })).toBe("cancelled");
    expect(saveBlob).not.toHaveBeenCalled();
  });
});

describe("PdfActions", () => {
  it("« Télécharger le PDF » enregistre le fichier", async () => {
    const load = vi.fn(async () => PDF);
    renderWithClient(<PdfActions load={load} title="Reçu" className="" />);
    await userEvent.click(screen.getByRole("button", { name: t.download }));
    await waitFor(() => expect(saveBlob).toHaveBeenCalledWith(PDF.blob, PDF.filename));
  });

  it("« Partager » sans partage de fichier : WhatsApp s'ouvre au clic, puis le PDF se télécharge", async () => {
    stubShare(false);
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const load = vi.fn(async () => PDF);
    renderWithClient(
      <PdfActions load={load} title="Reçu" fallback="https://wa.me/?text=Merci" className="" />,
    );
    await userEvent.click(screen.getByRole("button", { name: t.share }));
    expect(open).toHaveBeenCalledWith("https://wa.me/?text=Merci", "_blank", "noopener,noreferrer");
    await waitFor(() => expect(saveBlob).toHaveBeenCalled());
    open.mockRestore();
  });

  it("« Partager » avec partage de fichier : aucune fenêtre WhatsApp", async () => {
    const share = stubShare(true);
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    renderWithClient(
      <PdfActions load={async () => PDF} title="Reçu" fallback="https://wa.me/" className="" />,
    );
    await userEvent.click(screen.getByRole("button", { name: t.share }));
    await waitFor(() => expect(share).toHaveBeenCalled());
    expect(open).not.toHaveBeenCalled();
    open.mockRestore();
  });
});
