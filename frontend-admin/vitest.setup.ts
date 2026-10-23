import "@testing-library/jest-dom/vitest";

// jsdom n'a pas ResizeObserver, qu'observent les groupes radio et le Popover de Radix.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;
