import "@testing-library/jest-dom/vitest"
import { act, render, renderHook, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  InstallAppPromptView,
  type PwaInstallPromptViewState,
} from "@/components/pwa/InstallAppPrompt"
import {
  PWA_INSTALL_DISMISS_COOLDOWN_MS,
  PWA_INSTALL_DISMISSED_AT_KEY,
  isIosLikeNavigator,
  isStandaloneDisplay,
  usePwaInstall,
} from "@/hooks/usePwaInstall"

function createBeforeInstallPromptEvent(outcome: "accepted" | "dismissed" = "accepted") {
  const event = new Event("beforeinstallprompt", { cancelable: true }) as Event & {
    prompt: ReturnType<typeof vi.fn>
    userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>
  }

  Object.defineProperties(event, {
    preventDefault: { value: vi.fn(), configurable: true },
    prompt: { value: vi.fn().mockResolvedValue(undefined), configurable: true },
    userChoice: {
      value: Promise.resolve({ outcome, platform: "web" }),
      configurable: true,
    },
  })

  return event
}

function promptViewState(
  overrides: Partial<PwaInstallPromptViewState> = {},
): PwaInstallPromptViewState {
  return {
    isInstalled: false,
    promptKind: "native",
    canPrompt: true,
    promptInstall: vi.fn().mockResolvedValue(undefined),
    dismissPrompt: vi.fn(),
    ...overrides,
  }
}

beforeEach(() => {
  localStorage.clear()
  Object.defineProperties(window.navigator, {
    maxTouchPoints: { value: 0, configurable: true },
    platform: { value: "Linux x86_64", configurable: true },
    standalone: { value: false, configurable: true },
    userAgent: { value: "Mozilla/5.0", configurable: true },
  })
})

function mockDisplayMode(matches: boolean) {
  const listeners = new Set<(event: Event) => void>()
  const mediaQuery = {
    matches,
    media: "(display-mode: standalone)",
    onchange: null,
    addEventListener: vi.fn((_event: string, listener: (event: Event) => void) => {
      listeners.add(listener)
    }),
    removeEventListener: vi.fn((_event: string, listener: (event: Event) => void) => {
      listeners.delete(listener)
    }),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } as unknown as MediaQueryList

  Object.defineProperty(window, "matchMedia", {
    value: vi.fn(() => mediaQuery),
    configurable: true,
  })

  return {
    mediaQuery,
    setMatches(nextMatches: boolean) {
      Object.defineProperty(mediaQuery, "matches", {
        value: nextMatches,
        configurable: true,
      })
      listeners.forEach((listener) => listener(new Event("change")))
    },
  }
}

describe("PWA install foundation", () => {
  // AC-meta.fe-ia-nav.21
  it("AC22.20.1 keeps install manifest on the canonical home-screen launch contract", () => {
    const manifest = JSON.parse(
      readFileSync(resolve(process.cwd(), "public/site.webmanifest"), "utf8"),
    )

    expect(manifest.id).toBe("/")
    expect(manifest.start_url).toBe("/")
    expect(manifest.scope).toBe("/")
    expect(manifest.display).toBe("standalone")
    expect(manifest.icons).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ src: "/icon-192.png", sizes: "192x192", type: "image/png" }),
        expect.objectContaining({ src: "/icon-512.png", sizes: "512x512", type: "image/png" }),
        expect.objectContaining({ src: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }),
      ]),
    )
  })

  // AC-meta.fe-ia-nav.22
  it("AC22.20.2 captures Android beforeinstallprompt and invokes the deferred native prompt", async () => {
    const { result } = renderHook(() => usePwaInstall())
    const event = createBeforeInstallPromptEvent("accepted")

    act(() => {
      window.dispatchEvent(event)
    })

    expect(event.preventDefault).toHaveBeenCalled()
    await waitFor(() => expect(result.current.promptKind).toBe("native"))
    expect(result.current.canPrompt).toBe(true)

    await act(async () => {
      await result.current.promptInstall()
    })

    expect(event.prompt).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(result.current.isInstalled).toBe(true))
  })

  it("AC22.20.2 records app-level install prompt dismissal outside business pages", () => {
    const { result } = renderHook(() => usePwaInstall())

    act(() => {
      result.current.dismissPrompt()
    })

    expect(localStorage.getItem(PWA_INSTALL_DISMISSED_AT_KEY)).toMatch(/^\d+$/)
    expect(result.current.canPrompt).toBe(false)
    expect(result.current.promptKind).toBeNull()
  })

  it("AC22.20.2 preserves dismissal cooldown and handles dismissed native prompts", async () => {
    localStorage.setItem(PWA_INSTALL_DISMISSED_AT_KEY, String(Date.now()))
    const { result } = renderHook(() => usePwaInstall())
    const ignoredEvent = createBeforeInstallPromptEvent()

    act(() => {
      window.dispatchEvent(ignoredEvent)
    })

    expect(ignoredEvent.preventDefault).toHaveBeenCalled()
    expect(result.current.promptKind).toBeNull()

    localStorage.clear()
    const dismissedEvent = createBeforeInstallPromptEvent("dismissed")
    act(() => {
      window.dispatchEvent(dismissedEvent)
    })

    await waitFor(() => expect(result.current.promptKind).toBe("native"))
    await act(async () => {
      await result.current.promptInstall()
    })

    expect(dismissedEvent.prompt).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(PWA_INSTALL_DISMISSED_AT_KEY)).toMatch(/^\d+$/)
    expect(result.current.promptKind).toBeNull()
  })

  it("AC22.20.2 re-enables the app-shell prompt when dismissal cooldown expires", async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"))
    Object.defineProperties(window.navigator, {
      maxTouchPoints: { value: 1, configurable: true },
      platform: { value: "iPhone", configurable: true },
      userAgent: { value: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)", configurable: true },
    })
    localStorage.setItem(
      PWA_INSTALL_DISMISSED_AT_KEY,
      String(Date.now() - PWA_INSTALL_DISMISS_COOLDOWN_MS + 1000),
    )

    try {
      const { result } = renderHook(() => usePwaInstall())

      expect(result.current.promptKind).toBeNull()

      await act(async () => {
        vi.advanceTimersByTime(1001)
        await Promise.resolve()
      })

      expect(result.current.promptKind).toBe("ios")
    } finally {
      vi.useRealTimers()
    }
  })

  // AC-meta.fe-ia-nav.24
  it("AC22.20.4 detects iOS and standalone launch states without page code", async () => {
    mockDisplayMode(false)
    Object.defineProperties(window.navigator, {
      maxTouchPoints: { value: 1, configurable: true },
      platform: { value: "iPhone", configurable: true },
      userAgent: { value: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)", configurable: true },
    })

    expect(isIosLikeNavigator()).toBe(true)
    expect(isStandaloneDisplay()).toBe(false)

    Object.defineProperties(window.navigator, {
      maxTouchPoints: { value: 5, configurable: true },
      platform: { value: "MacIntel", configurable: true },
      userAgent: { value: "Mozilla/5.0 (Macintosh; Intel Mac OS X)", configurable: true },
    })
    expect(isIosLikeNavigator()).toBe(true)

    Object.defineProperty(window.navigator, "standalone", {
      value: true,
      configurable: true,
    })
    expect(isStandaloneDisplay()).toBe(true)
  })

  it("AC22.20.4 responds to appinstalled and display-mode standalone changes", async () => {
    const displayMode = mockDisplayMode(false)
    const { result, unmount } = renderHook(() => usePwaInstall())

    await act(async () => {
      await result.current.promptInstall()
    })
    expect(result.current.isInstalled).toBe(false)

    act(() => {
      window.dispatchEvent(new Event("appinstalled"))
    })
    await waitFor(() => expect(result.current.isInstalled).toBe(true))

    act(() => {
      displayMode.setMatches(true)
    })
    await waitFor(() => expect(result.current.isInstalled).toBe(true))

    const installedEvent = createBeforeInstallPromptEvent()
    act(() => {
      window.dispatchEvent(installedEvent)
    })
    expect(installedEvent.preventDefault).toHaveBeenCalled()
    expect(result.current.promptKind).toBeNull()

    unmount()
    expect(displayMode.mediaQuery.removeEventListener).toHaveBeenCalled()
  })

  // AC-meta.fe-ia-nav.23
  it("AC22.20.3 renders the Android install action from the global app-shell prompt", async () => {
    const user = userEvent.setup()
    const promptInstall = vi.fn().mockResolvedValue(undefined)

    render(
      <InstallAppPromptView
        state={promptViewState({
          promptKind: "native",
          canPrompt: true,
          promptInstall,
        })}
      />,
    )

    await user.click(screen.getByRole("button", { name: "Install app" }))
    expect(promptInstall).toHaveBeenCalledTimes(1)
    expect(screen.getByText("Install Finance Report")).toBeInTheDocument()
  })

  it("AC22.20.3 renders iOS Add to Home Screen guidance when no native prompt exists", () => {
    render(
      <InstallAppPromptView
        state={promptViewState({
          promptKind: "ios",
          canPrompt: false,
        })}
      />,
    )

    expect(screen.getByText("Add Finance Report to Home Screen")).toBeInTheDocument()
    expect(screen.getByText(/Share/)).toBeInTheDocument()
    expect(screen.getByText(/Add to Home Screen/)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Install app" })).not.toBeInTheDocument()
  })

  it("AC22.20.4 hides installed sessions and mounts the prompt only in the safe-area app shell", () => {
    const { container } = render(
      <InstallAppPromptView
        state={promptViewState({
          isInstalled: true,
          promptKind: "native",
          canPrompt: true,
        })}
      />,
    )

    expect(container).toBeEmptyDOMElement()

    const appShellSource = readFileSync(
      resolve(process.cwd(), "src/components/AppShell.tsx"),
      "utf8",
    )
    expect(appShellSource).toContain("pwa-safe-area-shell")
    expect(appShellSource).toMatch(/<InstallAppPrompt\b[^>]*\/>/)
  })
})
