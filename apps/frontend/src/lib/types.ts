/**
 * Shared Type Definitions
 */

export interface Account {
    id: string;
    name: string;
    code?: string;
    type: "ASSET" | "LIABILITY" | "EQUITY" | "INCOME" | "EXPENSE";
    currency: string;
    description?: string;
    parent_id?: string | null;
    is_active: boolean;
    balance?: number;
}

export interface AccountListResponse {
    items: Account[];
    total: number;
}

export interface JournalLine {
    id: string;
    account_id: string;
    direction: "DEBIT" | "CREDIT";
    amount: number;
    currency: string;
}

export interface JournalEntry {
    id: string;
    entry_date: string;
    memo: string;
    source_type: string;
    status: "draft" | "posted" | "reconciled" | "void";
    lines: JournalLine[];
    created_at: string;
    // Summary view properties
    total_amount?: number;
}

export interface JournalEntrySummary {
    id: string;
    entry_date: string;
    memo?: string | null;
    status: string;
    total_amount: number;
}

export interface JournalEntryListResponse {
    items: JournalEntry[];
    total: number;
}

export interface BankStatementTransaction {
    id: string;
    statement_id: string;
    txn_date: string;
    description: string;
    amount: number;
    direction: string;
    reference?: string | null;
    status: "pending" | "matched" | "unmatched";
    confidence: "high" | "medium" | "low";
    confidence_reason?: string | null;
    raw_text?: string | null;
    created_at: string;
    updated_at: string;
}

export interface BankStatementTransactionSummary {
    id: string;
    statement_id: string;
    txn_date: string;
    description: string;
    amount: number;
    direction: string;
    reference?: string | null;
    status: "pending" | "matched" | "unmatched";
}

export interface BankStatement {
    id: string;
    user_id: string;
    account_id?: string | null;
    file_path: string;
    original_filename: string;
    institution: string;
    account_last4?: string | null;
    currency?: string | null;
    period_start?: string | null;
    period_end?: string | null;
    opening_balance?: number | null;
    closing_balance?: number | null;
    status: "uploaded" | "parsing" | "parsed" | "approved" | "rejected";
    confidence_score?: number | null;
    balance_validated?: boolean | null;
    validation_error?: string | null;
    created_at: string;
    updated_at: string;
    transactions: BankStatementTransaction[];
}

export interface BankStatementListResponse {
    items: BankStatement[];
    total: number;
}

export interface ReportLine {
    account_id: string;
    name: string;
    type: string;
    parent_id?: string | null;
    amount: number | string;
}

export interface BalanceSheetResponse {
    as_of_date: string;
    currency: string;
    assets: ReportLine[];
    liabilities: ReportLine[];
    equity: ReportLine[];
    total_assets: number | string;
    total_liabilities: number | string;
    total_equity: number | string;
    equation_delta: number | string;
    is_balanced: boolean;
}

export interface IncomeStatementTrend {
    period_start: string;
    period_end: string;
    total_income: number | string;
    total_expenses: number | string;
    net_income: number | string;
}

export interface IncomeStatementResponse {
    start_date: string;
    end_date: string;
    currency: string;
    income: ReportLine[];
    expenses: ReportLine[];
    total_income: number | string;
    total_expenses: number | string;
    net_income: number | string;
    trends: IncomeStatementTrend[];
}

export interface ReconciliationStatsResponse {
    total_transactions: number;
    matched_transactions: number;
    unmatched_transactions: number;
    pending_review: number;
    auto_accepted: number;
    match_rate: number;
    score_distribution: Record<string, number>;
}

export interface UnmatchedTransactionsResponse {
    items: BankStatementTransactionSummary[];
    total: number;
}

export interface TrendPoint {
    period_start: string;
    period_end: string;
    amount: number | string;
}

export interface TrendResponse {
    account_id: string;
    currency: string;
    period: string;
    points: TrendPoint[];
}

export interface ReconciliationMatchResponse {
    id: string;
    bank_txn_id: string;
    journal_entry_ids: string[];
    match_score: number;
    score_breakdown: Record<string, number>;
    status: "auto_accepted" | "pending_review" | "accepted" | "rejected" | "superseded";
    transaction?: BankStatementTransactionSummary | null;
    entries: JournalEntrySummary[];
}

export interface ReconciliationMatchListResponse {
    items: ReconciliationMatchResponse[];
    total: number;
}
