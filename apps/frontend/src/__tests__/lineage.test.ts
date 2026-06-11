import { describe, expect, it } from "vitest"

import {
  anchorFromIdentifiers,
  anchorFromTypedIdentifier,
  lineageUrl,
  nodeLabel,
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

  it("nodeLabel renders a typed identifier label", () => {
    expect(nodeLabel({ entity_type: "journal_line", entity_id: UUID })).toBe(`journal_line:${UUID}`)
  })
})
