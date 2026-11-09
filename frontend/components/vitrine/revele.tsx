"use client";

import { useEffect } from "react";

/**
 * Apparition au défilement (prompt 38, A2, ADR 0116) : pose `data-vu` sur chaque élément
 * marqué `data-revele` quand il entre à l'écran, une seule fois, puis cesse de l'observer.
 *
 * Le masquage initial est dans `vitrine.module.css`, sous `@media (scripting: enabled) and
 * (prefers-reduced-motion: no-preference)` : sans script ou en mouvement réduit, tout est
 * visible d'emblée. Navigateur sans IntersectionObserver : tout est révélé tout de suite.
 */
export function Revele() {
  useEffect(() => {
    const elements = Array.from(document.querySelectorAll("[data-revele]:not([data-vu])"));
    if (!("IntersectionObserver" in window)) {
      for (const element of elements) element.setAttribute("data-vu", "");
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.setAttribute("data-vu", "");
          observer.unobserve(entry.target);
        }
      },
      { rootMargin: "0px 0px -8% 0px" },
    );
    for (const element of elements) observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return null;
}
