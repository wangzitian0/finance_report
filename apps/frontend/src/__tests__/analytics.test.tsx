import { render } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { Analytics, DEFAULT_OPENPANEL_API_URL } from "@/components/Analytics"

// Capture the props OpenPanelComponent is rendered with, without loading the
// real SDK (which would attempt to inject a script tag).
const openPanelProps = vi.hoisted(() => ({ current: null as Record<string, unknown> | null }))

vi.mock("@openpanel/nextjs", () => ({
  OpenPanelComponent: vi.fn((props: Record<string, unknown>) => {
    openPanelProps.current = props
    return <div data-testid="openpanel" />
  }),
}))

describe("Analytics", () => {
  it("renders nothing (no-op) when clientId is unset — safety contract", () => {
    openPanelProps.current = null
    const { container } = render(<Analytics />)
    expect(container).toBeEmptyDOMElement()
    expect(openPanelProps.current).toBeNull()
  })

  it("renders nothing when clientId is an empty / whitespace string", () => {
    openPanelProps.current = null
    const { container, rerender } = render(<Analytics clientId="" />)
    expect(container).toBeEmptyDOMElement()

    rerender(<Analytics clientId="   " />)
    expect(container).toBeEmptyDOMElement()
    expect(openPanelProps.current).toBeNull()
  })

  it("renders OpenPanelComponent with env-tagged global properties when configured", () => {
    render(
      <Analytics
        clientId="real-client-id"
        apiUrl="https://op.example.com/api"
        environment="staging"
      />,
    )

    expect(openPanelProps.current).toMatchObject({
      clientId: "real-client-id",
      apiUrl: "https://op.example.com/api",
      trackScreenViews: true,
      globalProperties: { environment: "staging" },
    })
  })

  it("defaults apiUrl and sends empty global properties when env not provided", () => {
    render(<Analytics clientId="real-client-id" />)

    expect(openPanelProps.current).toMatchObject({
      clientId: "real-client-id",
      apiUrl: DEFAULT_OPENPANEL_API_URL,
      globalProperties: {},
    })
  })

  it("error boundary swallows a render error from OpenPanelComponent (no rethrow)", async () => {
    const { OpenPanelComponent } = await import("@openpanel/nextjs")
    const mocked = vi.mocked(OpenPanelComponent)
    const original = mocked.getMockImplementation()
    mocked.mockImplementation(() => {
      throw new Error("boom")
    })
    // React logs caught errors to console.error; silence it for a clean run.
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {})

    // Must not throw — the boundary catches and renders null.
    const { container } = render(<Analytics clientId="real-client-id" />)
    expect(container).toBeEmptyDOMElement()

    errorSpy.mockRestore()
    if (original) {
      mocked.mockImplementation(original)
    }
  })
})
