import Link from "next/link";

import { BrokerageImportResponse } from "@/lib/types";

interface BrokerageImportResultBannerProps {
    importResult: BrokerageImportResponse;
}

export function BrokerageImportResultBanner({ importResult }: BrokerageImportResultBannerProps) {
    return (
        <div className="mb-4 p-4 border border-[var(--success)]/30 bg-[var(--success-muted)] rounded-lg" data-testid="import-result-banner">
            <div className="flex items-start gap-3">
                <svg className="w-5 h-5 text-[var(--success)] flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                <div className="flex-1 min-w-0">
                    <div className="font-medium text-[var(--success)] mb-2">
                        Brokerage positions imported successfully
                    </div>
                    <div className="text-sm space-y-0.5 mb-3">
                        <div><span className="text-muted">Broker:</span> <span className="font-medium">{importResult.broker}</span></div>
                        <div><span className="text-muted">Positions parsed:</span> <span className="font-medium">{importResult.parsed_positions}</span></div>
                        <div><span className="text-muted">New holdings created:</span> <span className="font-medium">{importResult.created_atomic_positions}</span></div>
                        <div><span className="text-muted">Holdings reconciled:</span> <span className="font-medium">{importResult.reconcile_created + importResult.reconcile_updated}</span></div>
                        {importResult.skipped > 0 && (
                            <div><span className="text-muted">Skipped:</span> <span className="font-medium">{importResult.skipped}</span></div>
                        )}
                    </div>
                    <Link href="/portfolio" className="btn-secondary text-sm" aria-label="View portfolio after import">
                        View Portfolio →
                    </Link>
                </div>
            </div>
        </div>
    );
}
