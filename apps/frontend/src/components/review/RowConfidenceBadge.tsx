import ConfidenceBadge from "@/components/ui/ConfidenceBadge";
import type { BankStatementTransaction } from "@/lib/types";

/**
 * The confidence badge of one statement row, in the statement table and in the low-confidence
 * review modal (#2647). The tier wins over the coarse confidence. A row with neither is "Not
 * rated": it is not shown as low.
 */
export function RowConfidenceBadge({ txn }: { txn: Pick<BankStatementTransaction, "confidence_tier" | "confidence"> }) {
  if (txn.confidence_tier) return <ConfidenceBadge tier={txn.confidence_tier} />;
  if (txn.confidence) {
    const variant = txn.confidence === "high" ? "badge-success" : txn.confidence === "medium" ? "badge-warning" : "badge-error";
    return <span className={`badge ${variant}`}>{txn.confidence}</span>;
  }
  return <span className="badge badge-muted">Not rated</span>;
}
