import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import StatementDetailPage from "@/app/(main)/statements/[id]/page";
import { apiFetch } from "@/lib/api";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({
    useParams: vi.fn(() => ({ id: "s1" })),
    useSearchParams: vi.fn(() => new URLSearchParams()),
}));

vi.mock("next/link", () => ({
    default: ({ href, children, ...rest }: { href: string; children: React.ReactNode; [key: string]: unknown }) => (
        <a href={href} {...rest}>{children}</a>
    ),
}));

const mockedApi = vi.mocked(apiFetch);

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

describe("StatementDetailPage - coverage additions", () => {
    beforeEach(() => vi.clearAllMocks());

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

        mockedApi.mockImplementation((path: string) => {
            if (String(path).includes(`/api/statements/`)) return Promise.resolve(stmt as any);
            return Promise.resolve(null as any);
        });

        renderReviewComponent(<StatementDetailPage /> as any);

        expect(await screen.findByText(/Parsing in progress/)).toBeInTheDocument();
    });

    it("shows statement not found when api returns null", async () => {
        mockedApi.mockImplementation((path: string) => {
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

        mockedApi
            .mockResolvedValueOnce(parsedBrokerageStatement as any)
            .mockResolvedValueOnce(importResult as any);

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

    it("AC17.8.3 shows actionable import error banner without exposing sensitive data", async () => {
        mockedApi
            .mockResolvedValueOnce(parsedBrokerageStatement as any)
            .mockRejectedValueOnce(
                new Error("Statement must be in PARSED or APPROVED status before importing"),
            );

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

    it("AC17.8.3 sanitizes sensitive URLs in import error messages", async () => {
        mockedApi
            .mockResolvedValueOnce(parsedBrokerageStatement as any)
            .mockRejectedValueOnce(
                new Error("Import failed: https://s3.example.com/private/token=abc123"),
            );

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
});
