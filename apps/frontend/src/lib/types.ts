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
    confidence_tier?: "TRUSTED" | "HIGH" | "MEDIUM" | "LOW" | null;
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
    currency?: string | null;
    balance_after?: number | null;
    status: "pending" | "matched" | "unmatched";
    confidence: "high" | "medium" | "low";
    confidence_tier?: "TRUSTED" | "HIGH" | "MEDIUM" | "LOW";
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
    confidence_tier?: "TRUSTED" | "HIGH" | "MEDIUM" | "LOW";
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
    parsing_progress?: number | null;
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

export interface AnnualizedIncomeResponse {
    annualized_salary: number | string;
    annualized_bonus: number | string;
    annualized_dividend: number | string;
    annualized_total: number | string;
    currency: string;
    as_of: string;
}

export interface RestrictedHolding {
    ticker: string;
    quantity: number | string;
    vesting_schedule?: string | null;
    unlock_date?: string | null;
    fair_value: number | string;
    currency: string;
}

export interface ValuationComponentsResponse {
    items: unknown[];
    total_assets: number | string;
    total_liabilities: number | string;
    net_worth_delta: number | string;
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

export type NetWorthRange = "1M" | "3M" | "6M" | "1Y" | "All";

export interface NetWorthTimeSeriesPoint {
    date: string;
    total_assets: number | string;
    total_liabilities: number | string;
    net_worth: number | string;
    currency: string;
}

export interface NetWorthTimeSeriesResponse {
    currency: string;
    granularity: "daily" | "monthly";
    points: NetWorthTimeSeriesPoint[];
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

export interface ManagedPosition {
    id: string;
    user_id: string;
    account_id: string;
    asset_identifier: string;
    quantity: string;
    cost_basis: string;
    acquisition_date: string;
    disposal_date?: string | null;
    status: "active" | "disposed";
    currency: string;
    position_metadata?: Record<string, unknown> | null;
    created_at: string;
    updated_at: string;
    account_name?: string | null;
}

export interface ManagedPositionListResponse {
    items: ManagedPosition[];
    total: number;
}

export interface ReconcilePositionsResponse {
    message: string;
    created: number;
    updated: number;
    disposed: number;
    skipped: number;
    skipped_assets: string[];
}

export type ManualValuationComponentType =
    | "property_value"
    | "mortgage_balance"
    | "cpf_balance"
    | "long_term_savings"
    | "tax_payable"
    | "tax_refund"
    | "insurance_cash_value"
    | "esop"
    | "rsu"
    | "stock_options"
    | "other_asset"
    | "other_liability";

export type ManualValuationLiquidityClass = "liquid" | "restricted" | "illiquid" | "liability";

export interface ManualValuationSnapshot {
    id: string;
    user_id: string;
    component_type: ManualValuationComponentType;
    liquidity_class: ManualValuationLiquidityClass;
    as_of_date: string;
    value: string;
    currency: string;
    source: string;
    notes?: string | null;
    recurrence_days?: number | null;
    reminder_date?: string | null;
    created_at: string;
    updated_at: string;
}

export interface ManualValuationSnapshotListResponse {
    items: ManualValuationSnapshot[];
    total: number;
}

// ── Portfolio Management (EPIC-017) ──────────────────────────────────

export interface PortfolioHolding {
    id: string;
    user_id: string;
    account_id: string;
    asset_identifier: string;
    quantity: string;
    cost_basis: string;
    market_value: string;
    unrealized_pnl: string;
    unrealized_pnl_percent: string;
    currency: string;
    acquisition_date: string;
    disposal_date?: string | null;
    status: "active" | "disposed";
    cost_basis_method?: "FIFO" | "LIFO" | "AvgCost" | null;
    account_name?: string | null;
    asset_type?: string | null;
    sector?: string | null;
    geography?: string | null;
}

export interface PortfolioSummaryResponse {
    total_market_value: string;
    total_cost_basis: string;
    total_unrealized_pnl: string;
    total_unrealized_pnl_percent: string;
    total_realized_pnl: string;
    total_realized_pnl_percent: string;
    net_pnl: string;
    net_pnl_percent: string;
    holdings_count: number;
    active_positions_count: number;
    disposed_positions_count: number;
    currency: string;
    realized_pnl_ytd: string;
    dividend_income_ytd: string;
}

export interface DividendEvent {
    id: string;
    ex_date: string;
    pay_date: string;
    amount: string;
    currency: string;
    reinvested: boolean;
}

export interface RealizedLot {
    lot_id: string;
    acquired_date?: string | null;
    sold_date: string;
    quantity: string;
    basis: string;
    proceeds: string;
    gain_loss: string;
    holding_period?: number | null;
    currency: string;
}

export interface PerformanceMetrics {
    xirr: string;
    time_weighted_return: string;
    money_weighted_return: string;
}

export interface AllocationBreakdown {
    category: string;
    value: string;
    percentage: string;
    count: number;
}

export interface PriceUpdate {
    asset_identifier: string;
    price: string;
    currency: string;
    price_date: string;
}

export interface PriceUpdateResponse {
    updated_count: number;
    results: Array<{
        success: boolean;
        message: string;
        asset_identifier: string;
        price_date: string;
        price: string;
        currency: string;
        source: string;
        created_at?: string | null;
    }>;
}

export interface ProcessingSummaryResponse {
    pending_count: number;
    pending_total: string;
    current_balance: string;
    currency: string;
    oldest_pending_date: string | null;
}

export interface ProcessingPendingItem {
    entry_id: string;
    from_account: string;
    to_account: string;
    amount: string;
    currency: string;
    initiated_date: string;
    days_outstanding: number;
    description: string;
}

export interface ProcessingPendingListResponse {
    items: ProcessingPendingItem[];
    total: number;
}

// ── Brokerage Import (EPIC-017 / statement import completion) ─────────────

export interface BrokerageImportResponse {
    broker: string;
    parsed_positions: number;
    created_atomic_positions: number;
    existing_atomic_positions: number;
    reconcile_created: number;
    reconcile_updated: number;
    reconcile_disposed: number;
    skipped: number;
}
