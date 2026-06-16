"use client";

import { useEffect } from "react";

import { initOtel } from "@/lib/otel";

/**
 * Mounts browser OpenTelemetry tracing exactly once on the client.
 *
 * Renders nothing. `initOtel` is a complete no-op until
 * `NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT` is configured, is idempotent, and
 * swallows its own errors — so this component is always safe to mount next to
 * `<Analytics>` in the root layout and never blocks render. Keeping the heavy
 * SDK behind a `"use client"` boundary + a `useEffect` keeps it out of the
 * server bundle.
 */
export function FrontendTelemetry(): null {
  useEffect(() => {
    initOtel();
  }, []);

  return null;
}

export default FrontendTelemetry;
