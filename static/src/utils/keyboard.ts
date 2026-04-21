export function trapFocus(container: HTMLElement): () => void {
  const focusableSelector =
    'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function handler(e: KeyboardEvent): void {
    if (e.key !== "Tab") return;

    const focusable = Array.from(
      container.querySelectorAll<HTMLElement>(focusableSelector)
    );
    if (focusable.length === 0) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  container.addEventListener("keydown", handler);
  return () => container.removeEventListener("keydown", handler);
}

export function onEscape(callback: () => void): () => void {
  function handler(e: KeyboardEvent): void {
    if (e.key === "Escape") {
      callback();
    }
  }

  document.addEventListener("keydown", handler);
  return () => document.removeEventListener("keydown", handler);
}
