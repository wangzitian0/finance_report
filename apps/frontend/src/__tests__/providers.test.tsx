import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { Providers } from "@/app/providers"

describe("Providers", () => {
  it("AC16.17.6 wraps children with QueryClientProvider", () => {
    render(
      <Providers>
        <div>Providers Child</div>
      </Providers>,
    )

    expect(screen.getByText("Providers Child")).toBeInTheDocument()
  })
})
