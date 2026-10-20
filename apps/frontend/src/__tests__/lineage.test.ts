import { describe, expect, it } from "vitest"

import {
  anchorFromIdentifiers,
  anchorFromTypedIdentifier,
  lineageUrl,
  nodeDisplayTitle,
  nodeLabel,
  nodeSourceHref,
  parseTypedIdentifier,
} from "@/lib/lineage"

const UUID = "11111111-1111-4111-8111-111111111111"

describe("lineage helpers (EPIC-022 AC22.3.4)", () => {
  it("parseTypedIdentifier accepts typed UUIDs and rejects malformed input", () => {
    expect(parseTypedIdentifier(`journal_line:${UUID}`)).toEqual({ type: "journal_line", id: UUID })
    expect(parseTypedIdentifier("no-separator")).toBeNull()
    expect(parseTypedIdentifier(":only")).toBeNull()
    expect(parseTypedIdentifier("journal_line:not-a-uuid")).toBeNull()
  })

  it("anchorFromTypedIdentifier maps known prefixes and ignores unknown ones", () => {
    expect(anchorFromTypedIdentifier(`journal_line:${UUID}`)).toEqual({
      entity_type: "journal_line",
      entity_id: UUID,
      node_kind: "ledger_line",
    })
    expect(anchorFromTypedIdentifier(`statement_transaction:${UUID}`)).toEqual({
      entity_type: "bank_statement_transaction",
      entity_id: UUID,
      node_kind: "extracted_record",
    })
    // Unknown prefix → no anchor (covers the unmapped branch).
    expect(anchorFromTypedIdentifier(`mystery_type:${UUID}`)).toBeNull()
    expect(anchorFromTypedIdentifier("garbage")).toBeNull()
  })

  it("anchorFromIdentifiers returns the first resolvable anchor", () => {
    expect(anchorFromIdentifiers([`mystery:${UUID}`, `atomic_transaction:${UUID}`])).toEqual({
      entity_type: "atomic_transaction",
      entity_id: UUID,
      node_kind: "atomic_fact",
    })
    expect(anchorFromIdentifiers([])).toBeNull()
    expect(anchorFromIdentifiers(["nope"])).toBeNull()
  })

  it("lineageUrl encodes the anchor and traversal params", () => {
    const url = lineageUrl({ entity_type: "journal_line", entity_id: UUID, node_kind: "ledger_line" })
    expect(url).toContain("/api/evidence/lineage?")
    expect(url).toContain("entity_type=journal_line")
    expect(url).toContain(`entity_id=${UUID}`)
    expect(url).toContain("node_kind=ledger_line")
    expect(url).toContain("direction=both")
    expect(url).toContain("max_depth=6")
    // node_kind is omitted when absent.
    expect(lineageUrl({ entity_type: "journal_line", entity_id: UUID })).not.toContain("node_kind")
  })

  it("nodeLabel renders a typed identifier label and includes original filename when present", () => {
    expect(nodeLabel({ entity_type: "journal_line", entity_id: UUID })).toBe(`journal_line:${UUID}`)
    expect(
      nodeLabel({
        entity_type: "uploaded_document",
        entity_id: UUID,
        properties: { original_filename: "DBS_2026_03.pdf" },
      }),
    ).toBe(`DBS_2026_03.pdf (uploaded_document:${UUID})`)
    expect(
      nodeLabel({
        entity_type: "uploaded_document",
        entity_id: UUID,
        properties: { filename: "export.csv" },
      }),
    ).toBe(`export.csv (uploaded_document:${UUID})`)
  })

  it("nodeDisplayTitle and nodeSourceHref resolve human-readable titles and links", () => {
    expect(
      nodeDisplayTitle({
        entity_type: "uploaded_document",
        entity_id: UUID,
        properties: { original_filename: "DBS_2026_03.pdf" },
      }),
    ).toBe("DBS_2026_03.pdf")
    expect(
      nodeDisplayTitle({
        entity_type: "atomic_transaction",
        entity_id: UUID,
        properties: { txn_date: "2026-03-15", amount: "120.50", currency: "SGD" },
      }),
    ).toBe("2026-03-15 · SGD 120.50")
    expect(
      nodeDisplayTitle({
        entity_type: "atomic_transaction",
        entity_id: UUID,
        properties: { txn_date: "2026-03-15", amount: "120.50" },
      }),
    ).toBe("2026-03-15 · 120.50")
    expect(nodeDisplayTitle({ entity_type: "journal_line", entity_id: UUID })).toBeNull()

    expect(
      nodeSourceHref({
        entity_type: "uploaded_document",
        entity_id: UUID,
        node_kind: "source_document",
      }),
    ).toBe("/statements")
    expect(
      nodeSourceHref({
        entity_type: "uploaded_document",
        entity_id: UUID,
        node_kind: "source_document",
        properties: { statement_id: "stmt-1" },
      }),
    ).toBe("/statements/stmt-1/review")
    expect(
      nodeSourceHref({
        entity_type: "journal_line",
        entity_id: UUID,
        node_kind: "ledger_line",
      }),
    ).toBe("/journal")
    expect(
      nodeSourceHref({
        entity_type: "atomic_transaction",
        entity_id: UUID,
        node_kind: "atomic_fact",
      }),
    ).toBe("/reconciliation")
    expect(
      nodeSourceHref({
        entity_type: "balance_sheet_line",
        entity_id: UUID,
        node_kind: "report_line",
      }),
    ).toBeNull()
  })
})
