import { useMemo, useSyncExternalStore } from "react"
import { vi } from "vitest"

/**
 * A URL-backed stand-in for `next/navigation` in Vitest.
 *
 * `router.replace` and `router.push` change the test URL and re-render every reader, as the
 * App Router does. Use it in a test file with:
 *   vi.mock("next/navigation", async () => (await import("./helpers/nextNavigation")).nextNavigationMock)
 */

let currentUrl = new URL("http://localhost/")
const listeners = new Set<() => void>()

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Set the URL of the test, for example `/reports?tab=cash-flow`. */
export function setTestUrl(path: string) {
  currentUrl = new URL(path, "http://localhost")
  listeners.forEach((listener) => listener())
}

/** The path and query of the test URL. */
export function testUrl(): string {
  return `${currentUrl.pathname}${currentUrl.search}`
}

export const routerReplace = vi.fn((href: string) => setTestUrl(href))
export const routerPush = vi.fn((href: string) => setTestUrl(href))

export const nextNavigationMock = {
  useSearchParams: () => {
    const search = useSyncExternalStore(subscribe, () => currentUrl.search)
    return useMemo(() => new URLSearchParams(search), [search])
  },
  usePathname: () => useSyncExternalStore(subscribe, () => currentUrl.pathname),
  useRouter: () => ({
    replace: routerReplace,
    push: routerPush,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useParams: () => ({}),
}
