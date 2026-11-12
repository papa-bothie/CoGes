import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProductSquare } from "@/components/kit/list-row";

import { photoUrl } from "./photo";

const PHOTO = {
  cloud_name: "coges-prod",
  public_id: "coges-production/2b1c/Xy_z-0aBc",
  version: 1700000001,
  width: 1600,
  height: 1067,
};

describe("adresse d'une photo (ADR 0121)", () => {
  it("vignette carrée, format et qualité choisis par Cloudinary", () => {
    expect(photoUrl(PHOTO, 104)).toBe(
      "https://res.cloudinary.com/coges-prod/image/upload/f_auto,q_auto,c_fill,g_auto,w_104,h_104/v1700000001/coges-production/2b1c/Xy_z-0aBc",
    );
  });

  it("image entière pour la fiche, taille bornée", () => {
    expect(photoUrl(PHOTO, 5000, "entiere")).toContain("/f_auto,q_auto,c_limit,w_1600/");
    expect(photoUrl(PHOTO, 2)).toContain("w_16,h_16");
  });

  it("toujours chez res.cloudinary.com, l'identifiant encodé", () => {
    const url = photoUrl({ ...PHOTO, cloud_name: "a/../b", public_id: "x/y z" }, 100);
    expect(url.startsWith("https://res.cloudinary.com/a%2F..%2Fb/")).toBe(true);
    expect(url).toContain("/x/y%20z");
  });
});

describe("vignette d'article", () => {
  it("la photo remplace le carré coloré, chargée à la demande", () => {
    const { container } = render(<ProductSquare name="Riz" size="grand" photo={PHOTO} />);
    const image = container.querySelector("img")!;
    expect(image.getAttribute("loading")).toBe("lazy");
    expect(image.getAttribute("src")).toContain("w_104,h_104");
    expect(image.getAttribute("alt")).toBe("");
  });

  it("sans photo, le carré coloré et son initiale restent", () => {
    const { container } = render(<ProductSquare name="Riz" size="grand" photo={null} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toBe("R");
  });
});
