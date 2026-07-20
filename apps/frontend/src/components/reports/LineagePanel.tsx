"use client";

import { useEffect, useState } from "react";

import Sheet from "@/components/ui/Sheet";
import { apiOperation } from "@/lib/api-client";
import { lineageQuery, nodeLabel, type LineageAnchor } from "@/lib/lineage";
import type {
  EvidenceLineageEdge,
  EvidenceLineageNode,
  EvidenceLineageResponse,
} from "@/lib/types";

interface LineagePanelState {
  isLoading: boolean;
  error: string | null;
  response: EvidenceLineageResponse | null;
}

const EMPTY_STATE: LineagePanelState = {
  isLoading: false,
  error: null,
  response: null,
};

function formatNodeKind(value: string): string {
  return value.replace(/_/g, " ");
}

function propertyValue(
  properties: EvidenceLineageNode["properties"],
  keys: string[],
): string | null {
  for (const key of keys) {
    const value = properties[key];
    if (typeof value === "string" && value.length > 0) return value;
    if (typeof value === "number" || typeof value === "boolean")
      return String(value);
  }
  return null;
}

function orderNodesAsPath(
  nodes: EvidenceLineageNode[],
  edges: EvidenceLineageEdge[],
): EvidenceLineageNode[] {
  if (nodes.length === 0 || edges.length === 0) return nodes;

  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const usableEdges = edges.filter(
    (edge) => nodeById.has(edge.from_node_id) && nodeById.has(edge.to_node_id),
  );
  if (usableEdges.length === 0) return nodes;

  const incoming = new Set(usableEdges.map((edge) => edge.to_node_id));
  const orderedOutgoing = new Map<string, EvidenceLineageEdge[]>();
  for (const edge of usableEdges) {
    const existing = orderedOutgoing.get(edge.from_node_id) ?? [];
    existing.push(edge);
    orderedOutgoing.set(edge.from_node_id, existing);
  }
  for (const list of orderedOutgoing.values()) {
    list.sort(
      (a, b) => b.depth - a.depth || a.relation.localeCompare(b.relation),
    );
  }

  const startId =
    usableEdges.find((edge) => !incoming.has(edge.from_node_id))
      ?.from_node_id ??
    usableEdges.sort((a, b) => b.depth - a.depth)[0]?.from_node_id;
  if (!startId) return nodes;

  const path: EvidenceLineageNode[] = [];
  const visited = new Set<string>();
  let currentId: string | undefined = startId;

  while (currentId && nodeById.has(currentId) && !visited.has(currentId)) {
    visited.add(currentId);
    path.push(nodeById.get(currentId)!);
    currentId = orderedOutgoing
      .get(currentId)
      ?.find((edge) => !visited.has(edge.to_node_id))?.to_node_id;
  }

  for (const node of nodes) {
    if (!visited.has(node.id)) path.push(node);
  }
  return path;
}

function lineageBadges(
  node: EvidenceLineageNode,
): Array<{ label: string; value: string }> {
  const source =
    propertyValue(node.properties, [
      "source_system",
      "source_type",
      "source_class",
    ]) ?? node.entity_type;
  const confidence = propertyValue(node.properties, [
    "confidence_tier",
    "confidence",
    "proof_level",
  ]);
  const version = propertyValue(node.properties, [
    "version",
    "record_version",
    "matrix_version",
  ]);
  return [
    { label: "Source", value: source },
    ...(confidence ? [{ label: "Confidence", value: confidence }] : []),
    ...(version ? [{ label: "Version", value: version }] : []),
  ];
}

export interface LineagePanelProps {
  /** Heading for the drawer (e.g. the report line / transaction description). */
  title: string;
  /** Lineage anchor to resolve; when null the panel is closed. */
  anchor: LineageAnchor | null;
  onClose: () => void;
}

/**
 * Reusable evidence-lineage drawer (EPIC-022 AC22.3.4). Given a lineage anchor
 * it fetches `/api/evidence/lineage` and renders the upstream/downstream chain
 * (ledger line → bank statement transaction → atomic fact → source document),
 * surfacing blockers and a graceful empty state when nothing is linked.
 */
export function LineagePanel({ title, anchor, onClose }: LineagePanelProps) {
  const [state, setState] = useState<LineagePanelState>(EMPTY_STATE);
  const anchorKey = anchor
    ? `${anchor.entity_type}:${anchor.entity_id}:${anchor.node_kind ?? ""}`
    : null;

  useEffect(() => {
    if (!anchor) {
      setState(EMPTY_STATE);
      return;
    }
    let active = true;
    setState({ isLoading: true, error: null, response: null });
    apiOperation("get_evidence_lineage_evidence_lineage_get", {
      query: lineageQuery(anchor),
    })
      .then((response) => {
        if (active) setState({ isLoading: false, error: null, response });
      })
      .catch((err: unknown) => {
        if (active) {
          setState({
            isLoading: false,
            error:
              err instanceof Error ? err.message : "Failed to load lineage",
            response: null,
          });
        }
      });
    return () => {
      active = false;
    };
  }, [anchor, anchorKey]);

  const { isLoading, error, response } = state;

  return (
    <Sheet
      isOpen={anchor !== null}
      onClose={onClose}
      title="Source lineage"
      width="max-w-lg"
    >
      <div className="space-y-4">
        <p className="text-sm font-medium break-words">{title}</p>

        {isLoading && (
          <p className="text-sm text-muted" role="status">
            Loading source lineage…
          </p>
        )}

        {error && <div className="alert-error text-sm">{error}</div>}

        {!isLoading && !error && response && (
          <>
            {response.blockers.length > 0 && (
              <div className="space-y-2" aria-label="Lineage blockers">
                {response.blockers.map((blocker) => (
                  <div key={blocker.code} className="alert-warning text-sm">
                    {blocker.message}
                  </div>
                ))}
              </div>
            )}

            {response.nodes.length === 0 ? (
              <p className="text-sm text-muted">
                No source records are linked to this amount yet.
              </p>
            ) : (
              <ol className="space-y-2" aria-label="Lineage path">
                {orderNodesAsPath(response.nodes, response.edges).map(
                  (node) => (
                    <li
                      key={node.id}
                      className="rounded-md border border-[var(--border)] bg-[var(--background-muted)]/40 p-3 text-sm"
                    >
                      <div className="font-medium">
                        {formatNodeKind(node.node_kind)}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {lineageBadges(node).map((badge) => (
                          <span
                            key={`${node.id}:${badge.label}`}
                            className="badge badge-muted"
                          >
                            {badge.label}: {badge.value}
                          </span>
                        ))}
                      </div>
                      <div className="mt-1 break-all font-mono text-xs text-muted">
                        {nodeLabel(node)}
                      </div>
                    </li>
                  ),
                )}
              </ol>
            )}
          </>
        )}
      </div>
    </Sheet>
  );
}
