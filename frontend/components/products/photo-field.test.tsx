import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import { renderWithClient } from "@/test/render";

import { PhotoField, photoRefusal } from "./photo-field";

vi.mock("@/lib/api/client", () => ({
  api: {
    GET: vi.fn(),
    PUT: vi.fn(async () => ({ response: new Response(null, { status: 200 }) })),
    DELETE: vi.fn(async () => ({ response: new Response(null, { status: 200 }) })),
  },
  unwrap: async <T,>(promise: Promise<T>) => promise,
}));

const PHOTO = {
  cloud_name: "coges-prod",
  public_id: "coges-production/2b1c/abc",
  version: 1,
  width: 800,
  height: 600,
};

function jpeg(name = "photo.jpg", type = "image/jpeg", size = 2048): File {
  return new File([new Uint8Array(size)], name, { type });
}

beforeEach(() => {
  vi.mocked(api.PUT).mockClear();
  vi.mocked(api.DELETE).mockClear();
  URL.createObjectURL = vi.fn(() => "blob:apercu");
  URL.revokeObjectURL = vi.fn();
});

describe("refus avant l'envoi", () => {
  it("SVG, PDF et fichiers démesurés", () => {
    expect(photoRefusal(jpeg("a.svg", "image/svg+xml"))).toMatch(/Format non pris en charge/);
    expect(photoRefusal(jpeg("a.pdf", "application/pdf"))).toMatch(/Format/);
    expect(photoRefusal({ type: "image/jpeg", size: 30 * 1024 * 1024 })).toMatch(/trop lourde/);
    expect(photoRefusal(jpeg())).toBeNull();
  });
});

describe("PhotoField", () => {
  it("propose la caméra arrière et la bibliothèque", () => {
    renderWithClient(<PhotoField name="Riz" productId="riz" />);
    expect(screen.getByTestId("photo-camera")).toHaveAttribute("capture", "environment");
    expect(screen.getByTestId("photo-library")).not.toHaveAttribute("capture");
    expect(screen.getByRole("button", { name: "Prendre une photo" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choisir une image" })).toBeInTheDocument();
  });

  it("sur la fiche : la photo part tout de suite, en multipart", async () => {
    const user = userEvent.setup();
    renderWithClient(<PhotoField name="Riz" productId="riz" />);
    await user.upload(screen.getByTestId("photo-camera"), jpeg());
    await waitFor(() => expect(api.PUT).toHaveBeenCalledTimes(1));
    const [path, init] = vi.mocked(api.PUT).mock.calls[0] as unknown as [
      string,
      { params: { path: { product_id: string } }; body: FormData },
    ];
    expect(path).toBe("/api/v1/products/{product_id}/photo");
    expect(init.params.path.product_id).toBe("riz");
    expect(init.body.get("file")).toBeInstanceOf(Blob);
  });

  it("nouvel article : la photo attend l'enregistrement, avec son aperçu", async () => {
    const user = userEvent.setup();
    const onPending = vi.fn();
    renderWithClient(<PhotoField name="Riz" onPending={onPending} />);
    await user.upload(screen.getByTestId("photo-library"), jpeg());
    expect(onPending).toHaveBeenCalledWith(expect.any(File));
    expect(api.PUT).not.toHaveBeenCalled();
    expect(screen.getByRole("img", { name: "Photo de Riz" })).toHaveAttribute("src", "blob:apercu");
    await user.click(screen.getByRole("button", { name: "Retirer" }));
    expect(onPending).toHaveBeenLastCalledWith(null);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:apercu");
  });

  it("une photo existante se retire", async () => {
    const user = userEvent.setup();
    renderWithClient(<PhotoField name="Riz" productId="riz" photo={PHOTO} />);
    expect(screen.getByRole("img", { name: "Photo de Riz" }).getAttribute("src")).toContain(
      "res.cloudinary.com",
    );
    await user.click(screen.getByRole("button", { name: "Retirer" }));
    await waitFor(() => expect(api.DELETE).toHaveBeenCalledTimes(1));
  });

  it("un SVG est refusé sans rien envoyer", async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderWithClient(<PhotoField name="Riz" productId="riz" />);
    await user.upload(screen.getByTestId("photo-library"), jpeg("a.svg", "image/svg+xml"));
    expect(await screen.findByText(/Format non pris en charge/)).toBeInTheDocument();
    expect(api.PUT).not.toHaveBeenCalled();
  });
});
