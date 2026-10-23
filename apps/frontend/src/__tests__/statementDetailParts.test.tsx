import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import {
    BrokerageImportResultBanner,
    StatementHeader,
} from "@/components/review/TransactionTable";
import { BankStatement, BrokerageImportResponse } from "@/lib/types";
import { currencyCodeOrDash as formatCode } from "@/lib/statusLabels";
import { formatPeriod } from "@/lib/date";

vi.mock("next/link", () => ({
    default: ({ href, children, ...rest }: { href: string; children: React.ReactNode; [key: string]: unknown }) => (
        <a href={href} {...rest}>{children}</a>
    ),
}));

const baseStatement: BankStatement = {
    id: "s1",
    user_id: "u1",
    account_id: null,
    account_last4: null,
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
    brokerage_import_failed: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    transactions: [],
};

function renderHeader(overrides: Partial<React.ComponentProps<typeof StatementHeader>> = {}) {
    const onBrokerageImport = vi.fn();
    const onRetry = vi.fn();
    const props: React.ComponentProps<typeof StatementHeader> = {
        statement: baseStatement,
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
    // AC-extraction.fe-ia-extraction.3
    it("AC22.17.3 renders title, status badge, description and confidence", () => {
        renderHeader();
        expect(screen.getByText("statement-jan.pdf")).toBeInTheDocument();
        expect(screen.getByText("parsed")).toBeInTheDocument();
        expect(screen.getByText(/DBS • SGD • 2026-01-01 to 2026-01-31/)).toBeInTheDocument();
        expect(screen.getByText(/Confidence 92% \(/)).toBeInTheDocument();
        expect(screen.queryByRole("link", { name: /review/i })).not.toBeInTheDocument();
    });

    it("#1609 labels mid and low confidence with text, not colour alone", () => {
        const { unmount } = render(
            <StatementHeader statement={{ ...baseStatement, confidence_score: 70 }} canImport={false} canRetry={false} importLoading={false} retryLoading={false} onBrokerageImport={vi.fn()} onRetry={vi.fn()} formatCode={formatCode} formatPeriod={formatPeriod} />,
        );
        expect(screen.getByText(/Confidence 70% \(\S+/)).toBeInTheDocument();
        unmount();
        renderHeader({ statement: { ...baseStatement, confidence_score: null } });
        expect(screen.queryByText(/Confidence/)).not.toBeInTheDocument();
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
