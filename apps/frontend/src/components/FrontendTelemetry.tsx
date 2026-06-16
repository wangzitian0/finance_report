"use client";

import { useEffect } from "react";

import { initOtel } from "@/lib/otel";

export interface FrontendTelemetryProps {
  /** OTLP/HTTP endpoint, supplied at runtime by the server layout. */
  endpoint?: string;
  /** `deployment.environment` (e.g. staging / production / pr-<N>). */
  environment?: string;
  /** Short git sha for `service.version`. */
  serviceVersion?: string;
}

/**
 * Mounts browser OpenTelemetry tracing exactly once on the client.
 *
 * Config arrives as props read server-side at request time (runtime injection,
 * mirroring `<Analytics>`) — NOT from client-inlined `NEXT_PUBLIC_*` — so a single
 * promoted image picks up each environment's values from its container env.
 * Renders nothing. `initOtel` is a complete no-op when `endpoint` is empty, is
 * idempotent, and swallows its own errors — always safe to mount, never blocks
 * render. The heavy SDK stays behind the `"use client"` + `useEffect` boundary,
 * out of the server bundle.
 */
export function FrontendTelemetry({
  endpoint,
  environment,
  serviceVersion,
}: FrontendTelemetryProps): null {
  useEffect(() => {
    initOtel({
      NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT: endpoint,
      NEXT_PUBLIC_DEPLOYMENT_ENVIRONMENT: environment,
      NEXT_PUBLIC_GIT_SHA: serviceVersion,
    });
  }, [endpoint, environment, serviceVersion]);

  return null;
}

export default FrontendTelemetry;
