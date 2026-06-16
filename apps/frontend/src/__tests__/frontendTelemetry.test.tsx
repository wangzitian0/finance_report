import { render } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

const initOtel = vi.hoisted(() => vi.fn())

vi.mock("@/lib/otel", () => ({ initOtel }))

import { FrontendTelemetry } from "@/components/FrontendTelemetry"

describe("FrontendTelemetry (AC23.1.1)", () => {
  it("AC23.1.1 renders nothing and calls initOtel once on mount", () => {
    initOtel.mockClear()
    const { container } = render(<FrontendTelemetry />)
    expect(container).toBeEmptyDOMElement()
    expect(initOtel).toHaveBeenCalledTimes(1)
  })
})
