"use client";

import { Component, type ReactNode } from "react";
import { OpenPanelComponent } from "@openpanel/nextjs";

/**
 * Default OpenPanel API endpoint for the self-hosted instance.
 *
 * Each environment can override this at runtime; this constant is only the
 * fallback used when no explicit `apiUrl` is supplied.
 */
export const DEFAULT_OPENPANEL_API_URL = "https://openpanel.zitian.party/api";

export interface AnalyticsProps {
  /**
   * OpenPanel client id. When empty/undefined the whole component is a
   * complete no-op (renders nothing). This is the safety contract that keeps
   * local/preview-without-config inert until OpenPanel onboarding provides a
   * real client id.
   */
  clientId?: string;
  /**
   * OpenPanel API endpoint. Defaults to the self-hosted instance.
   */
  apiUrl?: string;
  /**
   * Logical environment name (e.g. "staging", "production", "pr-47").
   * Tagged onto every tracked event via `globalProperties.environment` so PV
   * data can be split per environment even though staging/prod share the same
   * promoted Docker image.
   */
  environment?: string;
}

/**
 * Error boundary that SWALLOWS any mount/render error from its children and
 * renders nothing. Analytics must never affect the app: if OpenPanel's SDK
 * throws on mount/render, the page stays completely unaffected.
 */
class AnalyticsErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): { hasError: boolean } {
    // Swallow the error: flip to a render-nothing state. No rethrow.
    return { hasError: true };
  }

  componentDidCatch(): void {
    // Intentionally empty: do not surface or rethrow analytics failures.
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return null;
    }
    return this.props.children;
  }
}

/**
 * Non-blocking, fail-safe analytics wrapper.
 *
 * Guarantees:
 * 1. Config-gate — renders nothing when `clientId` is empty/unset, so the
 *    feature is a complete no-op until a client id is configured.
 * 2. Error boundary — any mount/render error from OpenPanel is caught and
 *    swallowed (renders null, never rethrows, never user-visible).
 * 3. Relies on the SDK's async script load + sendBeacon — render is never
 *    blocked and no tracking call is awaited on a critical path.
 */
export function Analytics({ clientId, apiUrl, environment }: AnalyticsProps) {
  // Config-gate: complete no-op when no client id is configured.
  if (!clientId || clientId.trim() === "") {
    return null;
  }

  return (
    <AnalyticsErrorBoundary>
      <OpenPanelComponent
        clientId={clientId}
        apiUrl={apiUrl && apiUrl.trim() !== "" ? apiUrl : DEFAULT_OPENPANEL_API_URL}
        trackScreenViews
        globalProperties={environment ? { environment } : {}}
      />
    </AnalyticsErrorBoundary>
  );
}

export default Analytics;
