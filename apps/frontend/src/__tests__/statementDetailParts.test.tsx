import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";

import { StatementHeader } from "@/app/(main)/statements/[id]/_components/StatementHeader";
import { StatementSummaryCards } from "@/app/(main)/statements/[id]/_components/StatementSummaryCards";
import { StatementTransactionsTable } from "@/app/(main)/statements/[id]/_components/StatementTransactionsTable";
import { BrokerageImportResultBanner } from "@/app/(main)/statements/[id]/_components/BrokerageImportResultBanner";
import { BankStatement, BankStatementTransaction, BrokerageImportResponse } from "@/lib/types";

vi.mock("next/link", () => ({
    default: ({ href, children, ...rest }: { href: string; children: React.ReactNode; [key: string]: unknown }) => (
        <a href={href} {...rest}>{children}</a>
    ),
}));

const baseStatement: BankStatement = {
    id: "s1",
    user_id: "u1",
    file_path: "/tmp/s1.pdf",
    original_filename: "statement-jan.pdf",
    institution: "DBS",
    currency: "SGD",
    period_start: "2026-01-01",
    period_end: "2026-01-31",
    opening_balance: "1000",
    closing_balance: "1500",
    status: "parsed",
    confidence_score: 92,
    balance_validated: true,
    validation_error: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    transactions: [],
};

const txn: BankStatementTransaction = {
    id: "t1",
    statement_id: "s1",
    txn_date: "2026-01-02",
    description: "Salary",
    reference: "R1",
    amount: "500",
    direction: "IN",
    currency: "SGD",
    balance_after: "1500",
    status: "matched",
    confidence: "high",
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
};

const formatCode = (currency?: string | null) => currency || "—";
const formatPeriod = (start?: string | null, end?: string | null) => {
    if (!start || !end) return "Parsing...";
    return `${start} to ${end}`;
};

function renderHeader(overrides: Partial<React.ComponentProps<typeof StatementHeader>> = {}) {
    const onBrokerageImport = vi.fn();
    const onRetry = vi.fn();
    const props: React.ComponentProps<typeof StatementHeader> = {
        statement: baseStatement,
        statementId: "s1",
        canImport: false,
        canRetry: false,
        importLoading: false,
        retryLoading: false,
        onBrokerageImport,
        onRetry,
        formatCode,
        formatPeriod,
        ...overrides,
    };
    render(<StatementHeader {...props} />);
    return { onBrokerageImport, onRetry };
}

describe("StatementHeader", () => {
    it("AC22.17.3 renders title, status badge, description and review link", () => {
        renderHeader();
        expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument();
        expect(screen.getByText("parsed")).toBeInTheDocument();
        expect(screen.getByText(/DBS • SGD • 2026-01-01 to 2026-01-31/)).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Start Review →" })).toHaveAttribute(
            "href",
            "/statements/s1/review",
        );
    });

    it("hides import and retry buttons when not allowed", () => {
        renderHeader({ canImport: false, canRetry: false });
        expect(
            screen.queryByRole("button", { name: /import brokerage positions to portfolio/i }),
        ).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Retry Parse" })).not.toBeInTheDocument();
    });

    it("shows import button and fires handler; idle label", () => {
        const { onBrokerageImport } = renderHeader({ canImport: true });
        const btn = screen.getByRole("button", { name: /import brokerage positions to portfolio/i });
        expect(btn).toHaveTextContent("Import to Portfolio");
        expect(btn).not.toBeDisabled();
        fireEvent.click(btn);
        expect(onBrokerageImport).toHaveBeenCalledTimes(1);
    });

    it("shows importing state (loading branch) and disables import button", () => {
        renderHeader({ canImport: true, importLoading: true });
        const btn = screen.getByRole("button", { name: /import brokerage positions to portfolio/i });
        expect(btn).toHaveTextContent("Importing...");
        expect(btn).toBeDisabled();
    });

    it("shows retry button, fires handler, and renders loading branch", () => {
        const { onRetry } = renderHeader({ canRetry: true });
        const btn = screen.getByRole("button", { name: "Retry Parse" });
        fireEvent.click(btn);
        expect(onRetry).toHaveBeenCalledTimes(1);

        renderHeader({ canRetry: true, retryLoading: true });
        const retryButtons = screen.getAllByRole("button", { name: "Retry Parse" });
        expect(retryButtons.some((b) => (b as HTMLButtonElement).disabled)).toBe(true);
    });

    it("applies status-specific badge classes for each status", () => {
        const statuses: Array<{ status: BankStatement["status"]; cls: string }> = [
            { status: "approved", cls: "badge-success" },
            { status: "rejected", cls: "badge-error" },
            { status: "parsed", cls: "badge-warning" },
            { status: "uploaded", cls: "badge-muted" },
        ];
        for (const { status, cls } of statuses) {
            const { unmount } = render(
                <StatementHeader
                    statement={{ ...baseStatement, status }}
                    statementId="s1"
                    canImport={false}
                    canRetry={false}
                    importLoading={false}
                    retryLoading={false}
                    onBrokerageImport={vi.fn()}
                    onRetry={vi.fn()}
                    formatCode={formatCode}
                    formatPeriod={formatPeriod}
                />,
            );
            expect(screen.getByText(status)).toHaveClass(cls);
            unmount();
        }
    });
});

describe("StatementSummaryCards", () => {
    it("AC22.17.3 renders balances, confidence and verified validation", () => {
        render(<StatementSummaryCards statement={baseStatement} />);
        expect(screen.getByText("Opening Balance")).toBeInTheDocument();
        expect(screen.getByText("Closing Balance")).toBeInTheDocument();
        expect(screen.getByText("92%")).toBeInTheDocument();
        // #1609: confidence is not color-only — a text label backs the colour.
        expect(screen.getByText("Good")).toBeInTheDocument();
        expect(screen.getByText("Verified")).toBeInTheDocument();
    });

    it("#1609 labels mid and low confidence with text, not colour alone", () => {
        const { rerender } = render(
            <StatementSummaryCards statement={{ ...baseStatement, confidence_score: 70 }} />,
        );
        expect(screen.getByText("Fair — review advised")).toBeInTheDocument();
        rerender(<StatementSummaryCards statement={{ ...baseStatement, confidence_score: 40 }} />);
        expect(screen.getByText("Low — review required")).toBeInTheDocument();
    });

    it("renders Parsing validation state and em-dash confidence when null", () => {
        render(
            <StatementSummaryCards
                statement={{ ...baseStatement, confidence_score: null, balance_validated: null }}
            />,
        );
        expect(screen.getByText("Parsing")).toBeInTheDocument();
        expect(screen.getByText("—%")).toBeInTheDocument();
    });

    it("renders Needs Review state with validation error", () => {
        render(
            <StatementSummaryCards
                statement={{
                    ...baseStatement,
                    balance_validated: false,
                    validation_error: "Balances do not match",
                }}
            />,
        );
        expect(screen.getByText("Needs Review")).toBeInTheDocument();
        expect(screen.getByText("Balances do not match")).toBeInTheDocument();
    });

    it("applies warning confidence color for mid score", () => {
        render(<StatementSummaryCards statement={{ ...baseStatement, confidence_score: 70 }} />);
        expect(screen.getByText("70%")).toHaveClass("text-[var(--warning)]");
    });

    it("applies error confidence color for low score", () => {
        render(<StatementSummaryCards statement={{ ...baseStatement, confidence_score: 30 }} />);
        expect(screen.getByText("30%")).toHaveClass("text-[var(--error)]");
    });
});

describe("StatementTransactionsTable", () => {
    it("renders empty state when no transactions", () => {
        render(<StatementTransactionsTable statement={baseStatement} />);
        expect(screen.getByText("No transactions found")).toBeInTheDocument();
        expect(screen.getByText("0 total")).toBeInTheDocument();
    });

    it("renders an inbound transaction row with positive amount", () => {
        render(
            <StatementTransactionsTable
                statement={{ ...baseStatement, transactions: [txn] }}
            />,
        );
        expect(screen.getByText("1 total")).toBeInTheDocument();
        expect(screen.getByText("Salary")).toBeInTheDocument();
        expect(screen.getByText("R1")).toBeInTheDocument();
        expect(screen.getByText("high")).toBeInTheDocument();
        expect(screen.getByText("matched")).toBeInTheDocument();
    });

    it("renders outbound, unmatched, medium/low rows and em-dashes for missing fields", () => {
        const outbound: BankStatementTransaction = {
            ...txn,
            id: "t2",
            direction: "OUT",
            reference: null,
            currency: null,
            balance_after: null,
            status: "unmatched",
            confidence: "medium",
        };
        const lowPending: BankStatementTransaction = {
            ...txn,
            id: "t3",
            status: "pending",
            confidence: "low",
        };
        render(
            <StatementTransactionsTable
                statement={{ ...baseStatement, transactions: [outbound, lowPending] }}
            />,
        );
        const rows = screen.getAllByRole("row");
        // header + 2 body rows
        expect(rows).toHaveLength(3);
        const outboundRow = rows[1];
        expect(within(outboundRow).getByText("-")).toBeInTheDocument();
        expect(within(outboundRow).getByText("unmatched")).toBeInTheDocument();
        expect(within(outboundRow).getByText("medium")).toBeInTheDocument();
        expect(screen.getByText("pending")).toBeInTheDocument();
        expect(screen.getByText("low")).toBeInTheDocument();
    });
});

describe("BrokerageImportResultBanner", () => {
    const result: BrokerageImportResponse = {
        broker: "Moomoo",
        parsed_positions: 5,
        created_atomic_positions: 3,
        existing_atomic_positions: 2,
        reconcile_created: 3,
        reconcile_updated: 2,
        reconcile_disposed: 0,
        skipped: 0,
    };

    it("AC22.17.3 renders import summary and portfolio link without skipped row", () => {
        render(<BrokerageImportResultBanner importResult={result} />);
        const banner = screen.getByTestId("import-result-banner");
        expect(banner).toHaveTextContent("Brokerage positions imported successfully");
        expect(banner).toHaveTextContent("Moomoo");
        expect(screen.getByRole("link", { name: /view portfolio after import/i })).toHaveAttribute(
            "href",
            "/portfolio",
        );
        expect(screen.queryByText("Skipped:")).not.toBeInTheDocument();
    });

    it("renders skipped row when skipped is greater than zero", () => {
        render(<BrokerageImportResultBanner importResult={{ ...result, skipped: 4 }} />);
        expect(screen.getByText("Skipped:")).toBeInTheDocument();
        expect(screen.getByText("4")).toBeInTheDocument();
    });
});
