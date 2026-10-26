"use client";

import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  DatabaseZap,
  LineChart,
  MessageSquareText,
  ShieldAlert,
} from "lucide-react";

import { humanizeWorkflowText } from "@/components/workflow/workflowFormat";
import routeMap from "@/lib/route-map.json";
import type { AdvisorSuggestion } from "@/lib/types";

const SAFE_ROUTE_FALLBACK = "/";

interface RouteEntry {
  path: string;
  state: string;
  into?: string;
}

// A route with no dynamic segment and no placeholder in its target.
const STATIC_ROUTES = new Map<string, RouteEntry>(
  (routeMap.routes as RouteEntry[])
    .filter((route) => !route.path.includes("[") && !route.into?.includes(":"))
    .map((route) => [route.path, route]),
);

// The `name=value` pairs that the route map names as redirect targets, e.g. `tab=package`.
const ROUTE_QUERY_PAIRS = new Set(
  (routeMap.routes as RouteEntry[]).flatMap((route) =>
    (route.into?.split("?")[1] ?? "").split("&").filter((pair) => pair && !pair.includes(":")),
  ),
);

/** Map an advisor href to a live internal route of `route-map.json`, or to `/`. */
export function safeAdvisorHref(href: string): string {
  const trimmed = href.trim();
  if (!trimmed.startsWith("/") || trimmed.startsWith("//")) return SAFE_ROUTE_FALLBACK;
  const [rawPath, query = ""] = trimmed.split("#")[0].split("?");
  const route = STATIC_ROUTES.get(rawPath.length > 1 ? rawPath.replace(/\/$/, "") : rawPath);
  if (!route || route.state === "shell") return SAFE_ROUTE_FALLBACK;
  if (route.state === "redirect") return route.into ?? SAFE_ROUTE_FALLBACK;
  const pairs = new Set(query.split("&").filter((pair) => ROUTE_QUERY_PAIRS.has(pair)));
  return pairs.size ? `${route.path}?${[...pairs].join("&")}` : route.path;
}

function titleForSuggestion(suggestion: AdvisorSuggestion): string {
  const tier = suggestion.confidence_tier.toLowerCase();
  if (tier.includes("blocked")) return "Readiness blocker";
  if (tier.includes("stale")) return "Refresh market data";
  if (tier.includes("review")) return "Needs review";
  if (tier.includes("deterministic")) return "Ready facts";
  return "Advisor signal";
}

function iconForSuggestion(suggestion: AdvisorSuggestion) {
  const tier = suggestion.confidence_tier.toLowerCase();
  if (tier.includes("blocked")) return AlertTriangle;
  if (tier.includes("stale")) return LineChart;
  if (tier.includes("review")) return ShieldAlert;
  if (tier.includes("deterministic")) return CheckCircle2;
  return DatabaseZap;
}

function promptForSuggestion(suggestion: AdvisorSuggestion): string {
  return [
    "Explain this Advisor Brief item using only the cited application facts.",
    `Basis: ${suggestion.basis}`,
    `Limitation: ${suggestion.limitation}`,
    `Sources: ${suggestion.source_refs?.join(", ") || "not provided"}`,
    `Next action: ${safeAdvisorHref(suggestion.next_action_href)}`,
  ].join("\n");
}

interface AdvisorBriefProps {
  suggestions: AdvisorSuggestion[];
  title?: string;
  description?: string;
  compact?: boolean;
  className?: string;
}

export function AdvisorBrief({
  suggestions,
  title = "Advisor Brief",
  description = "Application guidance from structured readiness, trust, workflow, market, portfolio, and cash-flow facts.",
  compact = false,
  className = "",
}: AdvisorBriefProps) {
  if (!suggestions.length) return null;

  return (
    <section className={`card p-5 ${className}`} aria-label="Advisor Brief" data-testid="advisor-brief">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold">{title}</h2>
          {!compact ? <p className="mt-2 max-w-3xl text-sm text-muted">{description}</p> : null}
        </div>
        <Link
          href={`/chat?prompt=${encodeURIComponent("Summarize my current Advisor Brief and list the safest next action.")}`}
          className="btn-secondary inline-flex shrink-0 items-center justify-center gap-2 text-sm"
        >
          <MessageSquareText className="h-4 w-4" aria-hidden="true" />
          Ask AI
        </Link>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        {suggestions.map((suggestion, index) => {
          const Icon = iconForSuggestion(suggestion);
          const safeHref = safeAdvisorHref(suggestion.next_action_href);
          const titleText = titleForSuggestion(suggestion);
          return (
            <article
              key={`${suggestion.confidence_tier}-${suggestion.basis}-${index}`}
              className="min-w-0 rounded-panel border border-border bg-surface-card p-4"
              data-testid={`advisor-brief-card-${index}`}
            >
              <div className="flex min-w-0 items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-accent-muted text-accent">
                  <Icon className="h-4 w-4" aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-semibold">{titleText}</h3>
                    <span className="badge badge-muted">{suggestion.confidence_tier}</span>
                  </div>
                  <p className="mt-2 break-words text-sm">{humanizeWorkflowText(suggestion.basis)}</p>
                  <p className="mt-2 break-words text-xs text-muted">{suggestion.limitation}</p>
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                {suggestion.source_refs && suggestion.source_refs.length > 0 ? (
                  suggestion.source_refs.map((source, sourceIndex) => (
                    <span key={`${source}-${sourceIndex}`} className="badge badge-info">
                      {source}
                    </span>
                  ))
                ) : (
                  <span className="badge badge-muted">source unavailable</span>
                )}
              </div>

              <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                <Link href={safeHref} className="btn-primary text-center text-sm">
                  Open next action
                </Link>
                <Link
                  href={`/chat?prompt=${encodeURIComponent(promptForSuggestion(suggestion))}`}
                  className="btn-secondary text-center text-sm"
                >
                  Ask about this
                </Link>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
