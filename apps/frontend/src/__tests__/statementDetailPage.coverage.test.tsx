import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, screen, fireEvent, waitFor } from "@testing-library/react";
import StatementDetailPage from "@/app/(main)/statements/[id]/page";
import { apiOperation } from "@/lib/api-client";
import { QueryClient } from "@tanstack/react-query";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }));
vi.mock("next/navigation", () => ({
    useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn() })),
    useParams: vi.fn(() => ({ id: "s1" })),
    useSearchParams: vi.fn(() => new URLSearchParams()),
}));

vi.mock("next/link", () => ({
    default: ({ href, children, ...rest }: { href: string; children: React.ReactNode; [key: string]: unknown }) => (
        <a href={href} {...rest}>{children}</a>
    ),
}));

const mockedApi = vi.mocked(apiOperation);

const parsedBrokerageStatement = {
    id: "s1",
    original_filename: "moomoo-2026-01.pdf",
    institution: "Moomoo",
    currency: "USD",
    period_start: "2026-01-01",
    period_end: "2026-01-31",
    opening_balance: null,
    closing_balance: null,
    status: "parsed",
    parsing_progress: 100,
    transactions: [],
};

const IMPORT_OP = "import_brokerage_statement_positions_statements__statement_id__brokerage_import_post";
const RETRY_OP = "retry_statement_parsing_statements__statement_id__retry_post";

function mockByOperation(statement: unknown, overrides: Record<string, () => Promise<unknown>> = {}) {
    mockedApi.mockImplementation(((operationId: string) => {
        const override = overrides[operationId];
        if (override) return override();
        if (operationId === "get_statement_statements__statement_id__get") return Promise.resolve(statement);
        return Promise.resolve(null);
    }) as any);
}

describe("StatementDetailPage - coverage additions", () => {
    beforeEach(() => vi.clearAllMocks());
    afterEach(() => {
        vi.useRealTimers();
    });

    it("renders parsing stopped alert and resume polling button", async () => {
        const stmt = {
            id: "s1",
            original_filename: "file.pdf",
            institution: "Bank",
            currency: "SGD",
            period_start: null,
            period_end: null,
            opening_balance: null,
            closing_balance: null,
            status: "parsing",
            parsing_progress: 10,
            transactions: [],
        };

        mockedApi.mockImplementation((operationId: string) => {
            if (operationId === "get_statement_statements__statement_id__get") return Promise.resolve(stmt as any);
            return Promise.resolve(null as any);
        });

        renderReviewComponent(<StatementDetailPage /> as any);

        expect(await screen.findByText(/Parsing in progress/)).toBeInTheDocument();
    });

    it("shows statement not found when api returns null", async () => {
        mockedApi.mockImplementation(() => {
            return Promise.resolve(null as any);
        });

        renderReviewComponent(<StatementDetailPage /> as any);

        expect(await screen.findByText(/Statement not found/)).toBeInTheDocument();
    });

    it("AC17.8.1 shows Import to Portfolio button for parsed statement", async () => {
        mockedApi.mockResolvedValueOnce(parsedBrokerageStatement as any);

        renderReviewComponent(<StatementDetailPage /> as any);

        await waitFor(() =>
            expect(
                screen.getByRole("button", { name: /import brokerage positions to portfolio/i }),
            ).toBeInTheDocument(),
        );
    });

    it("AC17.8.2 shows import result banner and portfolio link on success", async () => {
        const importResult = {
            broker: "Moomoo",
            parsed_positions: 5,
            created_atomic_positions: 3,
            existing_atomic_positions: 2,
            reconcile_created: 3,
            reconcile_updated: 2,
            reconcile_disposed: 0,
            skipped: 0,
        };

        mockByOperation(parsedBrokerageStatement, { [IMPORT_OP]: () => Promise.resolve(importResult) });

        renderReviewComponent(<StatementDetailPage /> as any);

        const importBtn = await screen.findByRole("button", {
            name: /import brokerage positions to portfolio/i,
        });
        fireEvent.click(importBtn);

        await waitFor(() =>
            expect(screen.getByTestId("import-result-banner")).toBeInTheDocument(),
        );
        const banner = screen.getByTestId("import-result-banner");
        expect(banner).toHaveTextContent("Brokerage positions imported successfully");
        expect(banner).toHaveTextContent("Moomoo");

        const portfolioLink = screen.getByRole("link", { name: /view portfolio after import/i });
        expect(portfolioLink).toHaveAttribute("href", "/portfolio");
    });

    // AC-portfolio.fe-assets2.13
    it("AC17.8.3 shows actionable import error banner without exposing sensitive data", async () => {
        mockByOperation(parsedBrokerageStatement, { [IMPORT_OP]: () => Promise.reject(
            new Error("Statement must be in PARSED or APPROVED status before importing"),
        ) });

        renderReviewComponent(<StatementDetailPage /> as any);

        const importBtn = await screen.findByRole("button", {
            name: /import brokerage positions to portfolio/i,
        });
        fireEvent.click(importBtn);

        await waitFor(() =>
            expect(screen.getByTestId("import-error-banner")).toBeInTheDocument(),
        );
        expect(screen.getByText("Brokerage Import Failed")).toBeInTheDocument();
        expect(
            screen.getByText(/Statement must be in PARSED or APPROVED status/),
        ).toBeInTheDocument();
    });

    // AC-extraction.fe-upload-layout.5
    it("AC-extraction.fe-upload-layout.5 marks the portfolio reads stale after a successful import on the statement page", async () => {
        mockByOperation(parsedBrokerageStatement, {
            [IMPORT_OP]: () => Promise.resolve({ broker: "Moomoo", parsed_positions: 1, created_atomic_positions: 1, existing_atomic_positions: 0, reconcile_created: 1, reconcile_updated: 0, reconcile_disposed: 0, skipped: 0 }),
        });
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const reads = [["portfolio-holdings", false, ""], ["portfolio-summary", ""], ["statements"], ["unrelated"]];
        for (const key of reads) client.setQueryData(key, { seeded: true });

        renderReviewComponent(<StatementDetailPage /> as any, client);
        fireEvent.click(await screen.findByRole("button", { name: /import brokerage positions to portfolio/i }));

        await waitFor(() => expect(screen.getByTestId("import-result-banner")).toBeInTheDocument());
        // The holdings and the statement list are stale; another read is not.
        expect(reads.map((key) => client.getQueryState(key)?.isInvalidated)).toEqual([true, true, true, false]);
    });

    it("AC17.8.3 sanitizes sensitive URLs in import error messages", async () => {
        mockByOperation(parsedBrokerageStatement, { [IMPORT_OP]: () => Promise.reject(
            new Error("Import failed: https://s3.example.com/private/token=abc123"),
        ) });

        renderReviewComponent(<StatementDetailPage /> as any);

        const importBtn = await screen.findByRole("button", {
            name: /import brokerage positions to portfolio/i,
        });
        fireEvent.click(importBtn);

        await waitFor(() =>
            expect(screen.getByTestId("import-error-banner")).toBeInTheDocument(),
        );
        // Sensitive URL replaced with [URL]
        expect(screen.queryByText(/s3\.example\.com/)).not.toBeInTheDocument();
        expect(screen.getByText(/\[URL\]/)).toBeInTheDocument();
    });

    // AC-portfolio.fe-assets2.15
    it("AC17.8.5 does not show Import to Portfolio for non-parsed statements", async () => {
        const uploadedStatement = {
            ...parsedBrokerageStatement,
            status: "uploaded",
        };
        mockedApi.mockResolvedValueOnce(uploadedStatement as any);

        renderReviewComponent(<StatementDetailPage /> as any);

        await waitFor(() =>
            expect(screen.getByText("moomoo-2026-01.pdf")).toBeInTheDocument(),
        );
        expect(
            screen.queryByRole("button", { name: /import brokerage positions to portfolio/i }),
        ).not.toBeInTheDocument();
    });

    it("test_AC8_13_48 stops stuck parsing auto-refresh and resumes polling on demand", async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));

        const parsingStatement = {
            ...parsedBrokerageStatement,
            status: "parsing",
            parsing_progress: 30,
            transactions: [],
        };
        mockedApi.mockResolvedValue(parsingStatement as any);

        renderReviewComponent(<StatementDetailPage /> as any);

        expect(await screen.findByText(/Parsing in progress/)).toBeInTheDocument();

        await act(async () => {
            vi.setSystemTime(new Date("2026-01-01T00:05:01Z"));
            await vi.advanceTimersByTimeAsync(3000);
        });

        expect(await screen.findByText("Auto-refresh Stopped")).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: "Resume Auto-Refresh" }));
        await waitFor(() =>
          expect(mockedApi).toHaveBeenCalledWith(
            "get_statement_statements__statement_id__get",
            expect.objectContaining({ signal: expect.any(AbortSignal) }),
          ),
        );
    });

    it("test_AC8_13_48 shows retry parsing errors for rejected statements", async () => {
        const rejectedStatement = {
            ...parsedBrokerageStatement,
            status: "rejected",
            validation_error: "Bad parse",
            transactions: [],
        };

        mockByOperation(rejectedStatement, { [RETRY_OP]: () => Promise.reject(new Error("retry failed")) });

        renderReviewComponent(<StatementDetailPage /> as any);

        await screen.findByText("Parsing Failed");
        fireEvent.click(screen.getAllByRole("button", { name: "Retry Parse" })[0]);

        await waitFor(() => expect(screen.getAllByText("retry failed").length).toBeGreaterThan(0));
        expect(mockedApi).toHaveBeenCalledWith(
            "retry_statement_parsing_statements__statement_id__retry_post",
            { path: { statement_id: "s1" } },
        );
    });

    it("handles delete statement confirmation and API call", async () => {
        mockedApi.mockImplementation((operationId: string) => {
            if (operationId === "delete_statement_statements__statement_id__delete") return Promise.resolve(null as any);
            return Promise.resolve(parsedBrokerageStatement as any);
        });

        renderReviewComponent(<StatementDetailPage /> as any);

        const deleteBtn = await screen.findByRole("button", { name: "Delete statement" });
        expect(deleteBtn).toBeInTheDocument();
        fireEvent.click(deleteBtn);

        // Test cancel
        const cancelBtn = screen.getByRole("button", { name: "Cancel" });
        fireEvent.click(cancelBtn);

        // Open again and confirm
        fireEvent.click(deleteBtn);
        const confirmBtn = await screen.findByRole("button", { name: "Delete" });
        fireEvent.click(confirmBtn);

        await waitFor(() => {
            expect(mockedApi).toHaveBeenCalledWith(
                "delete_statement_statements__statement_id__delete",
                expect.objectContaining({ path: { statement_id: "s1" } }),
            );
        });
    });

    it("handles delete statement error gracefully", async () => {
        mockedApi.mockImplementation((operationId: string) => {
            if (operationId === "delete_statement_statements__statement_id__delete") return Promise.reject(new Error("Failed to delete"));
            return Promise.resolve(parsedBrokerageStatement as any);
        });

        renderReviewComponent(<StatementDetailPage /> as any);

        const deleteBtn = await screen.findByRole("button", { name: "Delete statement" });
        fireEvent.click(deleteBtn);

        const confirmBtn = await screen.findByRole("button", { name: "Delete" });
        fireEvent.click(confirmBtn);

        await waitFor(() => {
            expect(screen.getByText("Failed to delete")).toBeInTheDocument();
        });
    });
});
