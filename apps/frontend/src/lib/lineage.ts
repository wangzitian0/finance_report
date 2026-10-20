export type LineageAnchor = {
  entity_type: string;
  entity_id: string;
  node_kind?: string;
};

// Shared evidence-lineage helpers (EPIC-022 AC22.3.4). Used by the Personal
// Report Package traceability appendix and by Balance Sheet / Income Statement
// amount drill-down, so both reach the same `/api/evidence/lineage` graph.

export const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

// Maps a typed identifier prefix to its lineage entity_type + node_kind.
const TYPED_IDENTIFIER_ANCHORS: Record<
  string,
  { entity_type: string; node_kind: string }
> = {
  journal_line: { entity_type: "journal_line", node_kind: "ledger_line" },
  uploaded_document: {
    entity_type: "uploaded_document",
    node_kind: "source_document",
  },
  statement_transaction: {
    entity_type: "bank_statement_transaction",
    node_kind: "extracted_record",
  },
  atomic_transaction: {
    entity_type: "atomic_transaction",
    node_kind: "atomic_fact",
  },
};

export function parseTypedIdentifier(
  identifier: string,
): { type: string; id: string } | null {
  const separator = identifier.indexOf(":");
  if (separator <= 0) return null;
  const type = identifier.slice(0, separator);
  const id = identifier.slice(separator + 1);
  if (!UUID_PATTERN.test(id)) return null;
  return { type, id };
}

export function anchorFromTypedIdentifier(
  identifier: string,
): LineageAnchor | null {
  const parsed = parseTypedIdentifier(identifier);
  if (!parsed) return null;
  const mapping = TYPED_IDENTIFIER_ANCHORS[parsed.type];
  if (!mapping) return null;
  return {
    entity_type: mapping.entity_type,
    entity_id: parsed.id,
    node_kind: mapping.node_kind,
  };
}

export function anchorFromIdentifiers(
  identifiers: readonly string[],
): LineageAnchor | null {
  for (const identifier of identifiers) {
    const anchor = anchorFromTypedIdentifier(identifier);
    if (anchor) return anchor;
  }
  return null;
}

export function lineageUrl(anchor: LineageAnchor): string {
  const params = new URLSearchParams({
    entity_type: anchor.entity_type,
    entity_id: anchor.entity_id,
  });
  if (anchor.node_kind) params.set("node_kind", anchor.node_kind);
  params.set("direction", "both");
  params.set("max_depth", "6");
  return `/api/evidence/lineage?${params.toString()}`;
}

export function lineageQuery(anchor: LineageAnchor) {
  return {
    entity_type: anchor.entity_type,
    entity_id: anchor.entity_id,
    node_kind: anchor.node_kind,
    direction: "both" as const,
    max_depth: 6,
  };
}

export function nodeDisplayTitle(node: {
  entity_type: string;
  entity_id: string;
  node_kind?: string;
  properties?: Record<string, unknown> | null;
}): string | null {
  const props = node.properties ?? {};
  const filename =
    (typeof props.original_filename === "string" &&
      props.original_filename.trim()) ||
    (typeof props.filename === "string" && props.filename.trim()) ||
    null;
  if (filename) return filename;

  const txnDate =
    typeof props.txn_date === "string" && props.txn_date.trim()
      ? props.txn_date.trim()
      : null;
  const amount =
    typeof props.amount === "string" && props.amount.trim()
      ? props.amount.trim()
      : null;
  const currency =
    typeof props.currency === "string" && props.currency.trim()
      ? props.currency.trim()
      : null;
  if (txnDate && amount) {
    return `${txnDate} · ${currency ? `${currency} ` : ""}${amount}`;
  }
  return null;
}

export function nodeSourceHref(node: {
  entity_type: string;
  entity_id: string;
  node_kind?: string;
  properties?: Record<string, unknown> | null;
}): string | null {
  const props = node.properties ?? {};
  const statementId =
    typeof props.statement_id === "string" && props.statement_id.trim()
      ? props.statement_id.trim()
      : null;
  if (
    node.node_kind === "source_document" ||
    node.entity_type === "uploaded_document" ||
    node.entity_type === "bank_statement_transaction"
  ) {
    return statementId ? `/statements/${statementId}/review` : "/statements";
  }
  if (
    node.node_kind === "ledger_line" ||
    node.node_kind === "ledger_entry" ||
    node.entity_type === "journal_line" ||
    node.entity_type === "journal_entry"
  ) {
    return "/journal";
  }
  if (
    node.node_kind === "atomic_fact" ||
    node.entity_type === "atomic_transaction"
  ) {
    return "/reconciliation";
  }
  return null;
}

export function nodeLabel(node: {
  entity_type: string;
  entity_id: string;
}): string {
  return `${node.entity_type}:${node.entity_id}`;
}
