"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Sheet } from "@/components/ui/Overlay";
import { apiOperation } from "@/lib/api-client";
import { formatCurrencyLocale } from "@/lib/audit/money";
import {
  anchorFromTypedIdentifier,
  lineageQuery,
  nodeDisplayTitle,
  nodeLabel,
  nodeSourceHref,
  type LineageAnchor,
} from "@/lib/lineage";
import type {
  AccountLineageResponse,
  EvidenceLineageEdge,
  EvidenceLineageNode,
  EvidenceLineageResponse,
} from "@/lib/types";

export interface AccountLineageTarget {
  accountId: string;
  accountName: string;
  asOfDate: string;
  startDate?: string;
  currency: string;
}

export interface LineagePanelProps {
  title: string;
  anchor: LineageAnchor | null;
  onClose: () => void;
}

function propertyValue(properties: EvidenceLineageNode["properties"], keys: string[]): string | null {
  for (const key of keys) {
    const val = properties[key];
    if (typeof val === "string" && val.length > 0) return val;
    if (typeof val === "number" || typeof val === "boolean") return String(val);
  }
  return null;
}

function orderNodesAsPath(nodes: EvidenceLineageNode[], edges: EvidenceLineageEdge[]): EvidenceLineageNode[] {
  if (nodes.length === 0 || edges.length === 0) return nodes;
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const usableEdges = edges.filter((e) => nodeById.has(e.from_node_id) && nodeById.has(e.to_node_id));
  if (usableEdges.length === 0) return nodes;

  const incoming = new Set(usableEdges.map((e) => e.to_node_id));
  const orderedOutgoing = new Map<string, EvidenceLineageEdge[]>();
  for (const edge of usableEdges) {
    const list = orderedOutgoing.get(edge.from_node_id) ?? [];
    list.push(edge);
    orderedOutgoing.set(edge.from_node_id, list);
  }
  for (const list of orderedOutgoing.values()) {
    list.sort((a, b) => b.depth - a.depth || a.relation.localeCompare(b.relation));
  }

  const startId =
    usableEdges.find((e) => !incoming.has(e.from_node_id))?.from_node_id ??
    usableEdges.sort((a, b) => b.depth - a.depth)[0]?.from_node_id;
  if (!startId) return nodes;

  const path: EvidenceLineageNode[] = [];
  const visited = new Set<string>();
  let currentId: string | undefined = startId;
  while (currentId && nodeById.has(currentId) && !visited.has(currentId)) {
    visited.add(currentId);
    path.push(nodeById.get(currentId)!);
    currentId = orderedOutgoing.get(currentId)?.find((e) => !visited.has(e.to_node_id))?.to_node_id;
  }
  for (const node of nodes) {
    if (!visited.has(node.id)) path.push(node);
  }
  return path;
}

function lineageBadges(node: EvidenceLineageNode): Array<{ label: string; value: string }> {
  const source = propertyValue(node.properties, ["source_system", "source_type", "source_class"]) ?? node.entity_type;
  const confidence = propertyValue(node.properties, ["confidence_tier", "confidence", "proof_level"]);
  const version = propertyValue(node.properties, ["version", "record_version", "matrix_version"]);
  return [
    { label: "Source", value: source },
    ...(confidence ? [{ label: "Confidence", value: confidence }] : []),
    ...(version ? [{ label: "Version", value: version }] : []),
  ];
}

export function LineagePanel({ title, anchor, onClose }: LineagePanelProps) {
  const [state, setState] = useState<{ isLoading: boolean; error: string | null; response: EvidenceLineageResponse | null }>({
    isLoading: false,
    error: null,
    response: null,
  });
  const anchorKey = anchor ? `${anchor.entity_type}:${anchor.entity_id}:${anchor.node_kind ?? ""}` : null;

  useEffect(() => {
    if (!anchor) {
      setState({ isLoading: false, error: null, response: null });
      return;
    }
    let active = true;
    setState({ isLoading: true, error: null, response: null });
    apiOperation("get_evidence_lineage_evidence_lineage_get", { query: lineageQuery(anchor) })
      .then((response) => {
        if (active) setState({ isLoading: false, error: null, response });
      })
      .catch((err: unknown) => {
        if (active) {
          setState({ isLoading: false, error: err instanceof Error ? err.message : "Failed to load lineage", response: null });
        }
      });
    return () => {
      active = false;
    };
  }, [anchor, anchorKey]);

  const { isLoading, error, response } = state;

  return (
    <Sheet isOpen={anchor !== null} onClose={onClose} title="Source lineage" width="max-w-lg">
      <div className="space-y-4">
        <p className="text-sm font-medium break-words">{title}</p>
        {isLoading && <p className="text-sm text-muted" role="status">Loading source lineage…</p>}
        {error && <div className="alert-error text-sm">{error}</div>}
        {!isLoading && !error && response && (
          <>
            {response.blockers.length > 0 && (
              <div className="space-y-2" aria-label="Lineage blockers">
                {response.blockers.map((b) => (
                  <div key={b.code} className="alert-warning text-sm">{b.message}</div>
                ))}
              </div>
            )}
            {response.nodes.length === 0 ? (
              <p className="text-sm text-muted">No source records are linked to this amount yet.</p>
            ) : (
              <ol className="space-y-2" aria-label="Lineage path">
                {orderNodesAsPath(response.nodes, response.edges).map((node) => {
                  const displayTitle = nodeDisplayTitle(node);
                  const sourceHref = nodeSourceHref(node);
                  return (
                    <li key={node.id} className="rounded-md border border-[var(--border)] bg-[var(--background-muted)]/40 p-3 text-sm">
                      <div className="flex items-center justify-between gap-2">
                        <div className="font-medium">{node.node_kind.replace(/_/g, " ")}</div>
                        {sourceHref && (
                          <Link href={sourceHref} className="inline-flex items-center gap-1 text-xs font-medium text-[var(--accent)] hover:underline">
                            {displayTitle ? `${displayTitle} ↗` : "Open source ↗"}
                          </Link>
                        )}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {lineageBadges(node).map((badge) => (
                          <span key={`${node.id}:${badge.label}`} className="badge badge-muted">
                            {badge.label}: {badge.value}
                          </span>
                        ))}
                      </div>
                      <div className="mt-1 break-all font-mono text-xs text-muted">{nodeLabel(node)}</div>
                    </li>
                  );
                })}
              </ol>
            )}
          </>
        )}
      </div>
    </Sheet>
  );
}

export function AccountLineageDrawer({ target, onClose }: { target: AccountLineageTarget | null; onClose: () => void }) {
  const [state, setState] = useState<{ isLoading: boolean; error: string | null; response: AccountLineageResponse | null }>({
    isLoading: false,
    error: null,
    response: null,
  });
  const [anchor, setAnchor] = useState<LineageAnchor | null>(null);
  const [anchorTitle, setAnchorTitle] = useState("");
  const targetKey = target ? `${target.accountId}:${target.asOfDate}:${target.startDate ?? ""}:${target.currency}` : null;

  useEffect(() => {
    setAnchor(null);
    if (!target) {
      setState({ isLoading: false, error: null, response: null });
      return;
    }
    let active = true;
    setState({ isLoading: true, error: null, response: null });
    apiOperation("account_lineage_reports_account_lineage_get", {
      query: { account_id: target.accountId, as_of_date: target.asOfDate, currency: target.currency, start_date: target.startDate },
    })
      .then((response) => {
        if (active) setState({ isLoading: false, error: null, response });
      })
      .catch((err: unknown) => {
        if (active) {
          setState({
            isLoading: false,
            error: err instanceof Error ? err.message : "Failed to load contributing transactions",
            response: null,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [target, targetKey]);

  const { isLoading, error, response } = state;

  return (
    <>
      <Sheet isOpen={target !== null} onClose={onClose} title={target ? `Sources · ${target.accountName}` : "Sources"} width="max-w-lg">
        <div className="space-y-3">
          {isLoading && <p className="text-sm text-muted" role="status">Loading contributing transactions…</p>}
          {error && <div className="alert-error text-sm">{error}</div>}
          {!isLoading && !error && response && (
            response.lines.length === 0 ? (
              <p className="text-sm text-muted">No source transactions contribute to this balance yet.</p>
            ) : (
              <ul className="divide-y divide-[var(--border)]" aria-label="Contributing transactions">
                {response.lines.map((line) => (
                  <li key={line.journal_line_id}>
                    <button
                      type="button"
                      className="flex w-full items-center justify-between gap-3 px-1 py-3 text-left text-sm hover:bg-[var(--background-muted)]/50"
                      onClick={() => {
                        setAnchor(anchorFromTypedIdentifier(`journal_line:${line.journal_line_id}`));
                        setAnchorTitle(line.memo || "Journal line");
                      }}
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{line.memo || "Journal line"}</span>
                        <span className="block text-xs text-muted">{line.entry_date}</span>
                      </span>
                      <span className="shrink-0 font-medium tabular-nums inline-flex items-center gap-1.5">
                        <span>{formatCurrencyLocale(line.amount, response.currency)}</span>
                        <span aria-hidden="true" className="text-xs text-[var(--accent)]">›</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )
          )}
        </div>
      </Sheet>
      <LineagePanel anchor={anchor} title={anchorTitle} onClose={() => setAnchor(null)} />
    </>
  );
}
