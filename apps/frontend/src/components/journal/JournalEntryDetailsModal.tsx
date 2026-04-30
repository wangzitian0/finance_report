"use client";

import DetailDialog from "@/components/ui/DetailDialog";
import AuditTrailPanel from "@/components/AuditTrailPanel";
import { formatCurrencyLocale } from "@/lib/currency";
import { formatDateDisplay } from "@/lib/date";
import { JournalEntry } from "@/lib/types";

interface JournalEntryDetailsModalProps {
    entry: JournalEntry | null;
    isOpen: boolean;
    onClose: () => void;
}

export default function JournalEntryDetailsModal({
    entry,
    isOpen,
    onClose,
}: JournalEntryDetailsModalProps) {
    if (!entry) return null;

    const totalDebits = entry.lines
        .filter((l) => l.direction === "DEBIT")
        .reduce((sum, l) => sum + l.amount, 0);
    const totalCredits = entry.lines
        .filter((l) => l.direction === "CREDIT")
        .reduce((sum, l) => sum + l.amount, 0);

    const baseCurrency = entry.lines[0]?.currency || "SGD";

    return (
        <DetailDialog isOpen={isOpen} onClose={onClose} title="Journal Entry Details" maxWidth="max-w-2xl">
            <div className="space-y-6">
                <div className="grid grid-cols-2 gap-6">
                    <div className="space-y-4">
                        <div>
                            <p className="text-xs text-muted mb-1">Date</p>
                            <p className="font-medium">{formatDateDisplay(entry.entry_date)}</p>
                        </div>
                        <div>
                            <p className="text-xs text-muted mb-1">Status</p>
                            <span className={`badge ${entry.status === "posted" ? "badge-success" :
                                entry.status === "reconciled" ? "badge-primary" :
                                    entry.status === "void" ? "badge-error" :
                                        "badge-muted"
                                }`}>
                                {entry.status}
                            </span>
                        </div>
                    </div>
                    <div className="space-y-4">
                        <div>
                            <p className="text-xs text-muted mb-1">Source Type</p>
                            <p className="font-medium capitalize">{entry.source_type.replace("_", " ")}</p>
                        </div>
                        <div>
                            <p className="text-xs text-muted mb-1">Created At</p>
                            <p className="font-medium">{new Date(entry.created_at).toLocaleString()}</p>
                        </div>
                    </div>
                    <div className="col-span-2">
                        <p className="text-xs text-muted mb-1">Memo</p>
                        <p className="text-sm bg-[var(--background-muted)]/50 p-3 rounded-md border border-[var(--border)] italic">
                            {entry.memo || "No memo"}
                        </p>
                    </div>
                </div>

                <div>
                    <h4 className="font-semibold mb-3">Lines</h4>
                    <div className="border border-[var(--border)] rounded-lg overflow-hidden">
                        <table className="w-full text-sm text-left">
                            <thead className="bg-[var(--background-muted)]/50 text-muted font-medium border-b border-[var(--border)]">
                                <tr>
                                    <th className="px-4 py-2">Account</th>
                                    <th className="px-4 py-2">Direction</th>
                                    <th className="px-4 py-2 text-right">Amount</th>
                                    <th className="px-4 py-2">Currency</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-[var(--border)]">
                                {entry.lines.map((line) => (
                                    <tr key={line.id} className={line.direction === "DEBIT" ? "bg-[var(--success-muted)]/5" : "bg-[var(--error-muted)]/5"}>
                                        <td className="px-4 py-3 font-mono text-xs">{line.account_id}</td>
                                        <td className="px-4 py-3">
                                            <span className={`badge ${line.direction === "DEBIT" ? "badge-success" : "badge-error"}`}>
                                                {line.direction}
                                            </span>
                                        </td>
                                        <td className={`px-4 py-3 text-right font-semibold ${line.direction === "DEBIT" ? "text-[var(--success)]" : "text-[var(--error)]"}`}>
                                            {formatCurrencyLocale(line.amount, line.currency)}
                                        </td>
                                        <td className="px-4 py-3 text-muted">{line.currency}</td>
                                    </tr>
                                ))}
                            </tbody>
                            <tfoot className="bg-[var(--background-muted)]/30 font-bold border-t border-[var(--border)]">
                                <tr>
                                    <td colSpan={2} className="px-4 py-3 text-right text-muted">Totals</td>
                                    <td className="px-4 py-3">
                                        <div className="flex flex-col items-end gap-1">
                                            <div className="text-[var(--success)]">
                                                <span className="text-[10px] uppercase mr-1">DR:</span>
                                                {formatCurrencyLocale(totalDebits, baseCurrency)}
                                            </div>
                                            <div className="text-[var(--error)]">
                                                <span className="text-[10px] uppercase mr-1">CR:</span>
                                                {formatCurrencyLocale(totalCredits, baseCurrency)}
                                            </div>
                                        </div>
                                    </td>
                                    <td className="px-4 py-3 text-muted">{baseCurrency}</td>
                                </tr>
                            </tfoot>
                        </table>
                    </div>
                </div>
                <AuditTrailPanel transactionId={entry.id} />
            </div>
        </DetailDialog>
    );
}
