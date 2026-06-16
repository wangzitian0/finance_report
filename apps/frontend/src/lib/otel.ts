/**
 * Browser OpenTelemetry tracing → SigNoz (OTLP/HTTP).
 *
 * Design contract (mirrors `components/Analytics.tsx`): config-gated,
 * non-blocking, and "never breaks the app". The whole module is a complete
 * no-op until `NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT` is set, so local /
 * preview-without-config runs stay inert until infra2 wires the per-env ingest
 * endpoint and DNS.
 *
 * Everything network-bound goes through the OTLP exporter only — this module
 * issues no raw browser network call of its own (the API-client red line still
 * applies; the exporter is the single sanctioned egress).
 *
 * The file is split into exhaustively unit-testable *pure helpers*
 * (`scrubUrl`, `sanitizeAttributes`, `resolveOtelConfig`) plus a thin `initOtel`
 * that wires the SDK. The pure helpers carry the PII-scrubbing contract and are
 * covered directly; `initOtel` is exercised against a mocked SDK.
 *
 * The SDK is imported statically (not via `require`). It is kept out of the
 * server bundle by importing this module only from a `"use client"` component
 * (`components/FrontendTelemetry.tsx`), so the heavy graph lands in the client
 * chunk only.
 */

import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { registerInstrumentations } from "@opentelemetry/instrumentation";
import { DocumentLoadInstrumentation } from "@opentelemetry/instrumentation-document-load";
import { FetchInstrumentation } from "@opentelemetry/instrumentation-fetch";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { BatchSpanProcessor, WebTracerProvider } from "@opentelemetry/sdk-trace-web";
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from "@opentelemetry/semantic-conventions";
import * as webVitalsModule from "web-vitals";

const SERVICE_NAME = "finance-report-frontend";

/** Resolved, validated configuration for the browser tracer. */
export interface OtelConfig {
  /** OTLP/HTTP traces endpoint (e.g. https://otel.zitian.party/v1/traces). */
  endpoint: string;
  /** Logical environment name (staging / production / pr-N). */
  environment: string;
  /** Deployed git SHA, used as `service.version`. */
  serviceVersion: string;
}

/**
 * Read the browser OTel configuration from `NEXT_PUBLIC_*` env vars.
 *
 * Returns `null` when the OTLP endpoint is empty/unset — the single config
 * gate that keeps the SDK a complete no-op. `environment` / `serviceVersion`
 * are best-effort tags and default to `"unknown"` when absent so a span is
 * never dropped just because a non-critical attribute is missing.
 *
 * Accepts an explicit `env` map for testability; defaults to `process.env`.
 */
export function resolveOtelConfig(
  env: Record<string, string | undefined> = process.env,
): OtelConfig | null {
  const endpoint = env.NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT?.trim();
  if (!endpoint) {
    return null;
  }
  return {
    endpoint,
    environment: env.NEXT_PUBLIC_DEPLOYMENT_ENVIRONMENT?.trim() || "unknown",
    serviceVersion: env.NEXT_PUBLIC_GIT_SHA?.trim() || "unknown",
  };
}

/**
 * Strip PII from a captured URL: drop the query string and fragment, keeping
 * only origin + path. Bank/account/amount values frequently ride in query
 * params, so they must never reach the collector.
 *
 * Falls back to a coarse, lossless-of-PII truncation for inputs the URL parser
 * rejects (relative paths, malformed values): everything from the first `?`
 * or `#` is removed.
 */
export function scrubUrl(rawUrl: string): string {
  if (!rawUrl) {
    return rawUrl;
  }
  try {
    const parsed = new URL(rawUrl);
    parsed.search = "";
    parsed.hash = "";
    // `toString()` re-appends a trailing "?" only when search is non-empty;
    // since we cleared it, origin + pathname is the clean result.
    return parsed.origin + parsed.pathname;
  } catch {
    // Not an absolute URL (or unparseable): manually cut query + fragment.
    const queryIdx = rawUrl.indexOf("?");
    const hashIdx = rawUrl.indexOf("#");
    const cutCandidates = [queryIdx, hashIdx].filter((i) => i >= 0);
    if (cutCandidates.length === 0) {
      return rawUrl;
    }
    return rawUrl.slice(0, Math.min(...cutCandidates));
  }
}

/** Span attribute keys whose values are URLs and must be scrubbed. */
const URL_ATTRIBUTE_KEYS = new Set([
  "http.url",
  "http.target",
  "url.full",
  "url.path",
  "url.query",
  "document.url",
  "location.href",
]);

/**
 * Lower-cased substrings that mark an attribute as sensitive. Any matching
 * attribute is dropped entirely (not just scrubbed) so emails, monetary
 * amounts, and account numbers never leave the browser.
 */
const SENSITIVE_KEY_FRAGMENTS = [
  "email",
  "amount",
  "balance",
  "account",
  "token",
  "secret",
  "password",
  "authorization",
  "cookie",
];

type AttributeValue = string | number | boolean | undefined | null;

/**
 * Sanitize a flat attribute bag before it is attached to a span:
 *  - URL-valued keys have their query/fragment scrubbed via {@link scrubUrl}.
 *  - keys matching a sensitive fragment are dropped wholesale.
 *  - `null` / `undefined` values are dropped.
 *
 * Pure and total — returns a new object and never throws.
 */
export function sanitizeAttributes(
  attributes: Record<string, AttributeValue>,
): Record<string, string | number | boolean> {
  const clean: Record<string, string | number | boolean> = {};
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === null) {
      continue;
    }
    const lowerKey = key.toLowerCase();
    if (SENSITIVE_KEY_FRAGMENTS.some((fragment) => lowerKey.includes(fragment))) {
      continue;
    }
    if (URL_ATTRIBUTE_KEYS.has(key) && typeof value === "string") {
      clean[key] = scrubUrl(value);
      continue;
    }
    clean[key] = value;
  }
  return clean;
}

/** Module-level guard so `initOtel` is idempotent across re-mounts/HMR. */
let initialized = false;

/** Reset the init guard. Test-only seam; not used by app code. */
export function resetOtelForTests(): void {
  initialized = false;
}

/**
 * Initialize browser tracing. Safe to call unconditionally and repeatedly:
 *  - returns `false` (no-op) when unconfigured or already initialized;
 *  - runs only in the browser (guards on `window`);
 *  - wraps everything in try/catch so a misbehaving SDK can never throw into
 *    the app's critical path;
 *  - uses a BatchSpanProcessor (async, batched) so no export is ever awaited.
 *
 * Accepts an explicit `env` for testability; defaults to `process.env`.
 */
export function initOtel(
  env: Record<string, string | undefined> = process.env,
): boolean {
  if (initialized) {
    return false;
  }
  if (typeof window === "undefined") {
    return false;
  }
  const config = resolveOtelConfig(env);
  if (!config) {
    return false;
  }

  initialized = true;
  try {
    startTracing(config);
    return true;
  } catch {
    // Swallow: telemetry must never surface an error to the user.
    return false;
  }
}

/**
 * The thin SDK-wiring core, factored out so `initOtel`'s guards stay readable.
 * Imports are eager (not dynamic) so the bundler tree-shakes them into the
 * client chunk only where `initOtel` is referenced (a client component).
 */
function startTracing(config: OtelConfig): void {
  const exporter = new OTLPTraceExporter({ url: config.endpoint });
  const resource = resourceFromAttributes({
    [ATTR_SERVICE_NAME]: SERVICE_NAME,
    [ATTR_SERVICE_VERSION]: config.serviceVersion,
    "deployment.environment": config.environment,
  });

  const provider = new WebTracerProvider({
    resource,
    spanProcessors: [new BatchSpanProcessor(exporter)],
  });
  provider.register();

  registerInstrumentations({
    instrumentations: [
      new FetchInstrumentation({
        // Scrub the captured URL so query-string PII never reaches the span.
        applyCustomAttributesOnSpan: makeUrlScrubHook(),
      }),
      new DocumentLoadInstrumentation(),
    ],
  });

  captureWebVitals(provider, config);
  installErrorHooks(provider, config);
}

/**
 * Build the fetch-instrumentation hook that rewrites the recorded URL
 * attribute to its scrubbed form. Returned as a standalone factory so the
 * scrubbing behavior is unit-testable without standing up the SDK.
 */
export function makeUrlScrubHook(): (
  span: { setAttribute(key: string, value: string): void },
  request: { url?: string } | string | RequestInit | Request,
) => void {
  return (span, request) => {
    const url =
      typeof request === "string"
        ? request
        : (request as { url?: string }).url;
    if (url) {
      span.setAttribute("http.url", scrubUrl(url));
    }
  };
}

/** Minimal shape of the tracer we need; keeps `any` out of the call sites. */
interface MinimalTracerProvider {
  getTracer(name: string): {
    startSpan(name: string): {
      setAttribute(key: string, value: string | number | boolean): void;
      recordException(error: Error): void;
      end(): void;
    };
  };
}

/**
 * Subscribe to web-vitals and emit each metric as a short-lived span carrying
 * sanitized attributes. Exported for direct unit testing with a fake provider
 * and a fake web-vitals module.
 */
export function captureWebVitals(
  provider: MinimalTracerProvider,
  config: OtelConfig,
  // Injection seam for tests; defaults to the real web-vitals module.
  webVitals: WebVitalsModule = webVitalsModule,
): void {
  const tracer = provider.getTracer(SERVICE_NAME);
  const report = (metric: { name: string; value: number }): void => {
    const span = tracer.startSpan(`web-vital.${metric.name}`);
    const attrs = sanitizeAttributes({
      "webvital.name": metric.name,
      "webvital.value": metric.value,
      "deployment.environment": config.environment,
    });
    for (const [key, value] of Object.entries(attrs)) {
      span.setAttribute(key, value);
    }
    span.end();
  };
  webVitals.onCLS?.(report);
  webVitals.onLCP?.(report);
  webVitals.onINP?.(report);
  webVitals.onFCP?.(report);
  webVitals.onTTFB?.(report);
}

interface WebVitalsModule {
  onCLS?: (cb: (m: { name: string; value: number }) => void) => void;
  onLCP?: (cb: (m: { name: string; value: number }) => void) => void;
  onINP?: (cb: (m: { name: string; value: number }) => void) => void;
  onFCP?: (cb: (m: { name: string; value: number }) => void) => void;
  onTTFB?: (cb: (m: { name: string; value: number }) => void) => void;
}

/**
 * Capture uncaught errors and unhandled promise rejections as span
 * exceptions. The captured message/URL are sanitized; emails/amounts/account
 * numbers are never attached. Exported for direct unit testing.
 */
export function installErrorHooks(
  provider: MinimalTracerProvider,
  config: OtelConfig,
  target: Pick<Window, "addEventListener"> = window,
): void {
  const tracer = provider.getTracer(SERVICE_NAME);
  const record = (error: Error, source: string): void => {
    const span = tracer.startSpan(`browser.${source}`);
    const attrs = sanitizeAttributes({
      "exception.source": source,
      "exception.type": error.name,
      "deployment.environment": config.environment,
      // The page URL is scrubbed of query/fragment before attaching.
      "location.href": scrubUrl(safeLocationHref()),
    });
    for (const [key, value] of Object.entries(attrs)) {
      span.setAttribute(key, value);
    }
    span.recordException(error);
    span.end();
  };

  target.addEventListener("error", (event) => {
    const err = (event as ErrorEvent).error;
    record(err instanceof Error ? err : new Error(String(err)), "onerror");
  });
  target.addEventListener("unhandledrejection", (event) => {
    const reason = (event as PromiseRejectionEvent).reason;
    record(
      reason instanceof Error ? reason : new Error(String(reason)),
      "unhandledrejection",
    );
  });
}

/** Read `location.href` without throwing in non-browser/odd environments. */
function safeLocationHref(): string {
  try {
    return window.location.href;
  } catch {
    return "";
  }
}
