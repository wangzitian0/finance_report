import { expect, it } from "vitest";
import { anchorFromIdentifiers, anchorFromTypedIdentifier, nodeDisplayTitle, nodeLabel, nodeSourceHref, parseTypedIdentifier } from "@/lib/lineage";
const U = "11111111-1111-4111-8111-111111111111", E = expect;
it("EPIC-022 AC22.3.4 lineage helpers", () => {
for (const [s, e] of [[`journal_line:${U}`, { type: "journal_line", id: U }], ["no-separator", null], [":only", null], ["journal_line:not-a-uuid", null]] as const) E(parseTypedIdentifier(s)).toEqual(e);
for (const [s, e] of [[`journal_line:${U}`, { entity_type: "journal_line", entity_id: U, node_kind: "ledger_line" }], [`statement_transaction:${U}`, { entity_type: "bank_statement_transaction", entity_id: U, node_kind: "extracted_record" }], [`mystery_type:${U}`, null], ["garbage", null]] as const) E(anchorFromTypedIdentifier(s)).toEqual(e);
E(anchorFromIdentifiers([`mystery:${U}`, `atomic_transaction:${U}`])).toEqual({ entity_type: "atomic_transaction", entity_id: U, node_kind: "atomic_fact" });
E([anchorFromIdentifiers([]), anchorFromIdentifiers(["nope"]), nodeLabel({ entity_type: "journal_line", entity_id: U })]).toEqual([null, null, `journal_line:${U}`]);
for (const [t, p, e] of [
["uploaded_document", { original_filename: "DBS.pdf" }, "DBS.pdf"],
["uploaded_document", { filename: "x.csv" }, "x.csv"],
["atomic_transaction", { txn_date: "2026-03-15", amount: "120.50", currency: "SGD" }, "2026-03-15 · SGD 120.50"],
["atomic_transaction", { txn_date: "2026-03-15", amount: "120.50" }, "2026-03-15 · 120.50"],
["journal_line", undefined, null],
] as const) E(nodeDisplayTitle({ entity_type: t, entity_id: U, ...(p ? { properties: p } : {}) })).toBe(e);
for (const [t, k, p, e] of [
["uploaded_document", "source_document", undefined, "/upload"],
["uploaded_document", "source_document", { statement_id: "s1" }, "/statements/s1"],
["journal_line", "ledger_line", undefined, "/journal"],
["atomic_transaction", "atomic_fact", undefined, "/reconciliation"],
["balance_sheet_line", "report_line", undefined, null],
] as const) E(nodeSourceHref({ entity_type: t, entity_id: U, node_kind: k, ...(p ? { properties: p } : {}) })).toBe(e);
});
