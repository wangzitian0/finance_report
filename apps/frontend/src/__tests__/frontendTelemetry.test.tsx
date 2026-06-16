import { render } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

const initOtel = vi.hoisted(() => vi.fn())

vi.mock("@/lib/otel", () => ({ initOtel }))

import { FrontendTelemetry } from "@/components/FrontendTelemetry"

describe("FrontendTelemetry (AC24.1.1)", () => {
  it("AC24.1.1 renders nothing and forwards runtime props to initOtel as the env map", () => {
    initOtel.mockClear()
    const { container } = render(
      <FrontendTelemetry
        endpoint="https://otel.zitian.party/v1/traces"
        environment="staging"
        serviceVersion="abc1234"
      />,
    )
    expect(container).toBeEmptyDOMElement()
    expect(initOtel).toHaveBeenCalledTimes(1)
    // Config comes from server-injected props (runtime), not client NEXT_PUBLIC.
    expect(initOtel).toHaveBeenCalledWith({
      NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: "https://otel.zitian.party/v1/traces",
      NEXT_PUBLIC_DEPLOYMENT_ENVIRONMENT: "staging",
      NEXT_PUBLIC_GIT_SHA: "abc1234",
    })
  })

  it("AC24.1.1 stays a no-op when no endpoint prop is supplied (gated)", () => {
    initOtel.mockClear()
    render(<FrontendTelemetry />)
    expect(initOtel).toHaveBeenCalledWith({
      NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: undefined,
      NEXT_PUBLIC_DEPLOYMENT_ENVIRONMENT: undefined,
      NEXT_PUBLIC_GIT_SHA: undefined,
    })
  })
})
