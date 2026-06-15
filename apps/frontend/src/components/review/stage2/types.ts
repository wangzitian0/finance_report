import type { MoneyValue } from "@/lib/types";

export interface ConsistencyCheck {
    id: string;
    check_type: string;
    status: string;
    related_txn_ids: string[];
    details: Record<string, unknown>;
    severity: string;
    resolved_at: string | null;
    resolution_note: string | null;
    created_at: string;
    updated_at: string;
}

export interface PendingMatch {
    id: string;
    match_score: number;
    status: string;
    created_at: string | null;
    description?: string;
    amount?: MoneyValue;
    txn_date?: string;
}

export interface Stage2Data {
    pending_matches: PendingMatch[];
    consistency_checks: ConsistencyCheck[];
    has_unresolved_checks: boolean;
}

export interface ProcessingSummary {
    pending_count: number;
    pending_total: MoneyValue;
    currency: string;
    oldest_pending_date: string | null;
}

export function getSeverityColor(severity: string) {
    switch (severity) {
        case "high":
            return "text-[var(--error)]";
        case "medium":
            return "text-[var(--warning)]";
        default:
            return "text-muted";
    }
}

export function getCheckTypeLabel(type: string) {
    switch (type) {
        case "duplicate":
            return "Duplicate";
        case "transfer_pair":
            return "Transfer Pair";
        case "anomaly":
            return "Anomaly";
        default:
            return type;
    }
}
