import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  captureWebVitals,
  initOtel,
  installErrorHooks,
  makeDocumentLoadScrubHook,
  makeUrlScrubHook,
  redactException,
  resetOtelForTests,
  resolveOtelConfig,
  sanitizeAttributes,
  scrubSpanUrlAttributes,
  scrubUrl,
  type OtelConfig,
} from "@/lib/otel"

// --- SDK mocks ------------------------------------------------------------
// initOtel's success path wires the real OTel SDK; mock every dependency so
// the test asserts on the wiring contract without standing up a real tracer.

const mocks = vi.hoisted(() => ({
  register: vi.fn(),
  startSpan: vi.fn(),
  registerInstrumentations: vi.fn(),
  exporterUrl: { current: undefined as string | undefined },
  resourceAttrs: { current: undefined as Record<string, unknown> | undefined },
  spanProcessors: { current: undefined as unknown },
}))

vi.mock("@opentelemetry/sdk-trace-web", () => ({
  WebTracerProvider: vi.fn(function (this: Record<string, unknown>, opts: Record<string, unknown>) {
    mocks.resourceAttrs.current = opts.resource as Record<string, unknown>
    mocks.spanProcessors.current = opts.spanProcessors
    this.register = mocks.register
    this.getTracer = () => ({ startSpan: mocks.startSpan })
  }),
  BatchSpanProcessor: vi.fn(function (this: Record<string, unknown>, exporter: unknown) {
    this.exporter = exporter
  }),
}))

vi.mock("@opentelemetry/exporter-trace-otlp-http", () => ({
  OTLPTraceExporter: vi.fn(function (this: Record<string, unknown>, opts: { url: string }) {
    mocks.exporterUrl.current = opts.url
  }),
}))

vi.mock("@opentelemetry/resources", () => ({
  resourceFromAttributes: vi.fn((attrs: Record<string, unknown>) => attrs),
}))

vi.mock("@opentelemetry/semantic-conventions", () => ({
  ATTR_SERVICE_NAME: "service.name",
  ATTR_SERVICE_VERSION: "service.version",
}))

vi.mock("@opentelemetry/instrumentation", () => ({
  registerInstrumentations: (arg: unknown) => mocks.registerInstrumentations(arg),
}))

vi.mock("@opentelemetry/instrumentation-fetch", () => ({
  FetchInstrumentation: vi.fn(function (this: Record<string, unknown>, opts: unknown) {
    this.opts = opts
  }),
}))

vi.mock("@opentelemetry/instrumentation-document-load", () => ({
  DocumentLoadInstrumentation: vi.fn(function (this: Record<string, unknown>) {}),
}))

vi.mock("web-vitals", () => ({
  onCLS: vi.fn(),
  onLCP: vi.fn(),
  onINP: vi.fn(),
  onFCP: vi.fn(),
  onTTFB: vi.fn(),
}))

const CONFIG: OtelConfig = {
  endpoint: "https://otel.zitian.party/v1/traces",
  environment: "staging",
  serviceVersion: "abc123",
}

beforeEach(() => {
  resetOtelForTests()
  vi.clearAllMocks()
})

afterEach(() => {
  resetOtelForTests()
})

describe("scrubUrl (AC24.1.2 — PII scrub)", () => {
  it("AC24.1.2 strips query string and fragment from an absolute URL", () => {
    expect(scrubUrl("https://app.example.com/reports?email=a@b.com&amount=1000#frag")).toBe(
      "https://app.example.com/reports",
    )
  })

  it("AC24.1.2 keeps a clean absolute URL unchanged", () => {
    expect(scrubUrl("https://app.example.com/reports")).toBe("https://app.example.com/reports")
  })

  it("AC24.1.2 cuts query/fragment from a relative/unparseable path", () => {
    expect(scrubUrl("/accounts/42?token=secret")).toBe("/accounts/42")
    expect(scrubUrl("/accounts/42#balance")).toBe("/accounts/42")
    expect(scrubUrl("/accounts/42")).toBe("/accounts/42")
  })

  it("AC24.1.2 returns empty input unchanged", () => {
    expect(scrubUrl("")).toBe("")
  })
})

describe("sanitizeAttributes (AC24.1.2 — PII scrub)", () => {
  it("AC24.1.2 drops sensitive keys (email/amount/account/...) entirely", () => {
    const clean = sanitizeAttributes({
      "user.email": "a@b.com",
      "txn.amount": 100,
      "bank.account_number": "123",
      Authorization: "Bearer x",
      "session.cookie": "c",
      safe: "kept",
    })
    expect(clean).toEqual({ safe: "kept" })
  })

  it("AC24.1.2 scrubs URL-valued attributes and drops null/undefined", () => {
    const clean = sanitizeAttributes({
      "http.url": "https://x.com/p?q=1#h",
      "document.url": "https://x.com/d?a=b",
      "missing": undefined,
      "empty": null,
      "ok.flag": true,
    })
    expect(clean).toEqual({
      "http.url": "https://x.com/p",
      "document.url": "https://x.com/d",
      "ok.flag": true,
    })
  })

  it("AC24.1.2 leaves a non-URL string URL key untouched when value is not a string", () => {
    // `http.target` is a URL key but here carries a number → passes through.
    expect(sanitizeAttributes({ "http.target": 8080 })).toEqual({ "http.target": 8080 })
  })
})

describe("resolveOtelConfig (AC24.1.1 — config gate)", () => {
  it("AC24.1.1 returns null when the OTLP endpoint is unset/blank", () => {
    expect(resolveOtelConfig({})).toBeNull()
    expect(resolveOtelConfig({ NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: "   " })).toBeNull()
  })

  it("AC24.1.1 resolves endpoint + env + version, defaulting tags to 'unknown'", () => {
    expect(
      resolveOtelConfig({ NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: "https://o/v1/traces" }),
    ).toEqual({
      endpoint: "https://o/v1/traces",
      environment: "unknown",
      serviceVersion: "unknown",
    })
    expect(
      resolveOtelConfig({
        NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: "https://o/v1/traces",
        NEXT_PUBLIC_DEPLOYMENT_ENVIRONMENT: "production",
        NEXT_PUBLIC_GIT_SHA: "deadbeef",
      }),
    ).toEqual({
      endpoint: "https://o/v1/traces",
      environment: "production",
      serviceVersion: "deadbeef",
    })
  })
})

describe("initOtel (AC24.1.1 — config-gated, non-blocking, idempotent)", () => {
  it("AC24.1.1 is a no-op (returns false) when unconfigured", () => {
    expect(initOtel({})).toBe(false)
    expect(mocks.register).not.toHaveBeenCalled()
  })

  it("AC24.1.1 wires the SDK once when configured, then is idempotent", () => {
    const env = {
      NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: CONFIG.endpoint,
      NEXT_PUBLIC_DEPLOYMENT_ENVIRONMENT: "staging",
      NEXT_PUBLIC_GIT_SHA: "abc123",
    }
    expect(initOtel(env)).toBe(true)
    expect(mocks.register).toHaveBeenCalledTimes(1)
    expect(mocks.exporterUrl.current).toBe(CONFIG.endpoint)
    expect(mocks.resourceAttrs.current).toMatchObject({
      "service.name": "finance-report-frontend",
      "service.version": "abc123",
      "deployment.environment": "staging",
    })
    expect(mocks.registerInstrumentations).toHaveBeenCalledTimes(1)

    // Second call: idempotent no-op.
    expect(initOtel(env)).toBe(false)
    expect(mocks.register).toHaveBeenCalledTimes(1)
  })

  it("AC24.1.1 is a no-op when window is undefined (server bundle guard)", () => {
    const original = globalThis.window
    // @ts-expect-error — simulate a non-browser (server) environment.
    delete globalThis.window
    try {
      expect(
        initOtel({ NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: CONFIG.endpoint }),
      ).toBe(false)
      expect(mocks.register).not.toHaveBeenCalled()
    } finally {
      globalThis.window = original
    }
  })

  it("AC24.1.1 swallows SDK errors and returns false (never throws)", () => {
    const env = { NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: CONFIG.endpoint }
    mocks.register.mockImplementationOnce(() => {
      throw new Error("sdk boom")
    })
    expect(() => initOtel(env)).not.toThrow()
    // initialized guard was set, so a follow-up call short-circuits.
    expect(initOtel(env)).toBe(false)
  })
})

describe("scrubSpanUrlAttributes (AC24.1.2)", () => {
  it("AC24.1.2 scrubs all URL-bearing attributes and blanks url.query", () => {
    const span = { setAttribute: vi.fn() }
    scrubSpanUrlAttributes(span, "https://x.com/p?secret=1#frag")
    expect(span.setAttribute).toHaveBeenCalledWith("url.query", "")
    for (const key of ["http.url", "http.target", "url.full", "document.url"]) {
      expect(span.setAttribute).toHaveBeenCalledWith(key, "https://x.com/p")
    }
  })

  it("AC24.1.2 still blanks url.query when no URL is present", () => {
    const span = { setAttribute: vi.fn() }
    scrubSpanUrlAttributes(span, undefined)
    expect(span.setAttribute).toHaveBeenCalledTimes(1)
    expect(span.setAttribute).toHaveBeenCalledWith("url.query", "")
  })
})

describe("makeUrlScrubHook (AC24.1.2)", () => {
  it("AC24.1.2 scrubs all URL attributes for a string request", () => {
    const span = { setAttribute: vi.fn() }
    makeUrlScrubHook()(span, "https://x.com/p?secret=1")
    expect(span.setAttribute).toHaveBeenCalledWith("http.url", "https://x.com/p")
    expect(span.setAttribute).toHaveBeenCalledWith("url.full", "https://x.com/p")
    expect(span.setAttribute).toHaveBeenCalledWith("url.query", "")
  })

  it("AC24.1.2 scrubs all URL attributes from a Request-like object", () => {
    const span = { setAttribute: vi.fn() }
    makeUrlScrubHook()(span, { url: "https://x.com/q?a=b#c" })
    expect(span.setAttribute).toHaveBeenCalledWith("http.target", "https://x.com/q")
    expect(span.setAttribute).toHaveBeenCalledWith("url.query", "")
  })

  it("AC24.1.2 blanks url.query even when no URL is present", () => {
    const span = { setAttribute: vi.fn() }
    makeUrlScrubHook()(span, {})
    expect(span.setAttribute).toHaveBeenCalledWith("url.query", "")
  })
})

describe("makeDocumentLoadScrubHook (AC24.1.2)", () => {
  it("AC24.1.2 scrubs the document URL attributes on the span", () => {
    const span = { setAttribute: vi.fn() }
    const original = Object.getOwnPropertyDescriptor(document, "documentURI")
    Object.defineProperty(document, "documentURI", {
      configurable: true,
      get: () => "https://x.com/page?token=abc#h",
    })
    try {
      makeDocumentLoadScrubHook()(span)
      expect(span.setAttribute).toHaveBeenCalledWith("document.url", "https://x.com/page")
      expect(span.setAttribute).toHaveBeenCalledWith("url.query", "")
    } finally {
      if (original) {
        Object.defineProperty(document, "documentURI", original)
      }
    }
  })

  it("AC24.1.2 falls back to location.href when documentURI is empty", () => {
    const span = { setAttribute: vi.fn() }
    const original = Object.getOwnPropertyDescriptor(document, "documentURI")
    const originalLoc = Object.getOwnPropertyDescriptor(window, "location")
    Object.defineProperty(document, "documentURI", { configurable: true, get: () => "" })
    Object.defineProperty(window, "location", {
      configurable: true,
      get: () => ({ href: "https://x.com/home?u=1" }),
    })
    try {
      makeDocumentLoadScrubHook()(span)
      expect(span.setAttribute).toHaveBeenCalledWith("document.url", "https://x.com/home")
    } finally {
      if (original) Object.defineProperty(document, "documentURI", original)
      if (originalLoc) Object.defineProperty(window, "location", originalLoc)
    }
  })

  it("AC24.1.2 tolerates document access throwing (safe blank)", () => {
    const span = { setAttribute: vi.fn() }
    const original = Object.getOwnPropertyDescriptor(document, "documentURI")
    Object.defineProperty(document, "documentURI", {
      configurable: true,
      get() {
        throw new Error("blocked")
      },
    })
    const originalLoc = Object.getOwnPropertyDescriptor(window, "location")
    Object.defineProperty(window, "location", {
      configurable: true,
      get() {
        throw new Error("blocked")
      },
    })
    try {
      expect(() => makeDocumentLoadScrubHook()(span)).not.toThrow()
      expect(span.setAttribute).toHaveBeenCalledWith("url.query", "")
    } finally {
      if (original) Object.defineProperty(document, "documentURI", original)
      if (originalLoc) Object.defineProperty(window, "location", originalLoc)
    }
  })
})

describe("redactException (AC24.1.3)", () => {
  it("AC24.1.3 keeps the error type but redacts the message/stack", () => {
    const err = new Error("user a@b.com owes $1,234 on account 999")
    expect(redactException(err)).toEqual({ name: "Error", message: "[redacted]" })
  })

  it("AC24.1.3 defaults a missing name to 'Error'", () => {
    expect(redactException({})).toEqual({ name: "Error", message: "[redacted]" })
    expect(redactException({ name: "" })).toEqual({ name: "Error", message: "[redacted]" })
    expect(redactException({ name: "TypeError" })).toEqual({
      name: "TypeError",
      message: "[redacted]",
    })
  })
})

describe("captureWebVitals (AC24.1.1)", () => {
  it("AC24.1.1 subscribes to vitals and emits a sanitized span per metric", () => {
    const setAttribute = vi.fn()
    const end = vi.fn()
    const provider = {
      getTracer: () => ({ startSpan: () => ({ setAttribute, recordException: vi.fn(), end }) }),
    }
    let captured: ((m: { name: string; value: number }) => void) | undefined
    const webVitals = {
      onCLS: (cb: (m: { name: string; value: number }) => void) => {
        captured = cb
      },
      onLCP: vi.fn(),
      onINP: vi.fn(),
      onFCP: vi.fn(),
      onTTFB: vi.fn(),
    }
    captureWebVitals(provider, CONFIG, webVitals)
    expect(captured).toBeDefined()
    captured?.({ name: "CLS", value: 0.1 })
    expect(setAttribute).toHaveBeenCalledWith("webvital.name", "CLS")
    expect(setAttribute).toHaveBeenCalledWith("webvital.value", 0.1)
    expect(end).toHaveBeenCalledTimes(1)
  })

  it("AC24.1.1 tolerates a partial web-vitals module (optional callbacks)", () => {
    const provider = {
      getTracer: () => ({
        startSpan: () => ({ setAttribute: vi.fn(), recordException: vi.fn(), end: vi.fn() }),
      }),
    }
    expect(() => captureWebVitals(provider, CONFIG, {})).not.toThrow()
  })
})

describe("installErrorHooks (AC24.1.3 — exceptions as span exceptions)", () => {
  function fakeProvider() {
    const recordException = vi.fn()
    const setAttribute = vi.fn()
    const end = vi.fn()
    return {
      recordException,
      setAttribute,
      end,
      provider: {
        getTracer: () => ({
          startSpan: () => ({ setAttribute, recordException, end }),
        }),
      },
    }
  }

  it("AC24.1.3 records window.onerror as a span exception with a scrubbed location", () => {
    const f = fakeProvider()
    const listeners: Record<string, (e: unknown) => void> = {}
    const target = {
      addEventListener: (type: string, cb: (e: unknown) => void) => {
        listeners[type] = cb
      },
    }
    installErrorHooks(f.provider, CONFIG, target as unknown as Window)
    const err = new Error("user a@b.com owes $1,234")
    listeners["error"]({ error: err } as ErrorEvent)
    // The raw Error must NOT be exported — only a redacted form (type kept).
    expect(f.recordException).toHaveBeenCalledWith({ name: "Error", message: "[redacted]" })
    expect(f.setAttribute).toHaveBeenCalledWith("exception.source", "onerror")
    expect(f.setAttribute).toHaveBeenCalledWith("exception.type", "Error")
    expect(f.end).toHaveBeenCalled()
  })

  it("AC24.1.3 records unhandledrejection, wrapping a non-Error reason", () => {
    const f = fakeProvider()
    const listeners: Record<string, (e: unknown) => void> = {}
    const target = {
      addEventListener: (type: string, cb: (e: unknown) => void) => {
        listeners[type] = cb
      },
    }
    installErrorHooks(f.provider, CONFIG, target as unknown as Window)
    listeners["unhandledrejection"]({ reason: "string failure" } as PromiseRejectionEvent)
    expect(f.recordException).toHaveBeenCalledTimes(1)
    // A non-Error reason is wrapped in Error then redacted — the raw string
    // ("string failure") must not appear in the exported exception.
    const recorded = f.recordException.mock.calls[0][0] as { name: string; message: string }
    expect(recorded).toEqual({ name: "Error", message: "[redacted]" })

    // And a non-Error onerror payload is also wrapped + redacted.
    listeners["error"]({ error: undefined } as ErrorEvent)
    expect(f.recordException).toHaveBeenCalledTimes(2)
    expect(f.recordException.mock.calls[1][0]).toEqual({ name: "Error", message: "[redacted]" })

    // An Error reason keeps its type through redaction.
    listeners["unhandledrejection"]({
      reason: new TypeError("bad"),
    } as PromiseRejectionEvent)
    expect(f.recordException.mock.calls[2][0]).toEqual({
      name: "TypeError",
      message: "[redacted]",
    })
  })

  it("AC24.1.3 tolerates window.location access throwing (safe href fallback)", () => {
    const f = fakeProvider()
    const listeners: Record<string, (e: unknown) => void> = {}
    const target = {
      addEventListener: (type: string, cb: (e: unknown) => void) => {
        listeners[type] = cb
      },
    }
    const originalLocation = Object.getOwnPropertyDescriptor(window, "location")
    Object.defineProperty(window, "location", {
      configurable: true,
      get() {
        throw new Error("location blocked")
      },
    })
    try {
      installErrorHooks(f.provider, CONFIG, target as unknown as Window)
      expect(() => listeners["error"]({ error: new Error("x") } as ErrorEvent)).not.toThrow()
      expect(f.recordException).toHaveBeenCalledTimes(1)
    } finally {
      if (originalLocation) {
        Object.defineProperty(window, "location", originalLocation)
      }
    }
  })
})
