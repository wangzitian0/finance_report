import { afterEach, beforeEach, describe, expect as E, it, vi } from "vitest";
import * as O from "@/lib/otel";
import * as F from "./helpers/shellTestFixtures";

const M = vi.hoisted(() => ({
  reg: vi.fn(),
  span: vi.fn(),
  regI: vi.fn(),
  url: { c: "" as string | undefined },
  res: { c: undefined as Record<string, unknown> | undefined },
}));
vi.mock("@opentelemetry/sdk-trace-web", () => ({
  WebTracerProvider: vi.fn(function (
    this: Record<string, unknown>,
    o: Record<string, unknown>,
  ) {
    M.res.c = o.resource as Record<string, unknown>;
    this.register = M.reg;
    this.getTracer = () => ({ startSpan: M.span });
  }),
  BatchSpanProcessor: vi.fn(function (
    this: Record<string, unknown>,
    e: unknown,
  ) {
    this.exporter = e;
  }),
}));
vi.mock("@opentelemetry/exporter-trace-otlp-http", () => ({
  OTLPTraceExporter: vi.fn(function (
    this: Record<string, unknown>,
    o: { url: string },
  ) {
    M.url.c = o.url;
  }),
}));
vi.mock("@opentelemetry/resources", () => ({
  resourceFromAttributes: vi.fn((a: Record<string, unknown>) => a),
}));
vi.mock("@opentelemetry/semantic-conventions", () => ({
  ATTR_SERVICE_NAME: "s",
  ATTR_SERVICE_VERSION: "v",
}));
vi.mock("@opentelemetry/instrumentation", () => ({
  registerInstrumentations: (a: unknown) => M.regI(a),
}));
vi.mock("@opentelemetry/instrumentation-fetch", () => ({
  FetchInstrumentation: vi.fn(),
}));
vi.mock("@opentelemetry/instrumentation-document-load", () => ({
  DocumentLoadInstrumentation: vi.fn(),
}));
vi.mock("web-vitals", () => ({
  onCLS: vi.fn(),
  onLCP: vi.fn(),
  onINP: vi.fn(),
  onFCP: vi.fn(),
  onTTFB: vi.fn(),
}));

describe("otel", () => {
  beforeEach(() => {
    O.resetOtelForTests();
    vi.clearAllMocks();
  });
  afterEach(() => O.resetOtelForTests());
  it.each(F.OTEL_SCRUB_CASES)("u%#", (i, o) => E(O.scrubUrl(i)).toBe(o));
  it.each(F.OTEL_RESOLVE_CASES)("c%#", (e, o) =>
    E(O.resolveOtelConfig(e)).toEqual(o),
  );
  it.each(F.OTEL_REDACT_CASES)("r%#", (err, n) =>
    E(O.redactException(err)).toEqual({ name: n, message: "[redacted]" }),
  );
  it.each(F.OTEL_URL_HOOK_CASES)("uh%#", (a, k, v) => {
    const s = { setAttribute: vi.fn() };
    O.makeUrlScrubHook()(s, a);
    if (k) E(s.setAttribute).toHaveBeenCalledWith(k, v);
  });
  it.each(F.OTEL_DOC_CASES)("dh%#", ({ defs, expected }) => {
    const s = { setAttribute: vi.fn() };
    F.withDefinedProps(defs, () => {
      E(() => O.makeDocumentLoadScrubHook()(s)).not.toThrow();
      if (expected)
        E(s.setAttribute).toHaveBeenCalledWith("document.url", expected);
    });
  });
  it("initOtel", () => F.runOtelInitChecks(O, M));
  it("hooks", () => F.runOtelSpanAndErrorChecks(O));
});
