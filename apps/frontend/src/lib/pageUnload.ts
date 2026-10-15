/**
 * Page teardown signal (#2473).
 *
 * A hard navigation aborts every in-flight `fetch`. The browser rejects each one
 * with `TypeError: Failed to fetch` while React does not unmount, so no effect
 * cleanup runs. That rejection is not an application failure and must not reach
 * `console.error`. `pagehide` fires before the abort, and `pageshow` clears the
 * flag when the browser restores the page from its back/forward cache.
 */
let unloading = false;

if (typeof window !== "undefined") {
  window.addEventListener("pagehide", () => {
    unloading = true;
  });
  window.addEventListener("pageshow", () => {
    unloading = false;
  });
}

export function isPageUnloading(): boolean {
  return unloading;
}
