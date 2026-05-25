import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import StatementReviewPage from "@/app/(main)/statements/[id]/review/page";
import { apiFetch } from "@/lib/api";

import { renderReviewComponent } from "./helpers/renderReviewComponent";

const pushMock = vi.fn();
const replaceMock = vi.fn();

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({
    useRouter: vi.fn(() => ({ replace: replaceMock, push: pushMock })),
    useParams: vi.fn(() => ({ id: "s1" })),
}));

const mockedApi = vi.mocked(apiFetch);

const baseStatement = {
    id: "s1",
    original_filename: "statement.pdf",
    institution: "DBS",
    currency: "SGD",
    period_start: "2024-01-01",
    period_end: "2024-01-31",
    opening_balance: 100,
    closing_balance: 120,
    status: "pending",
    stage1_status: null,
    balance_validation_result: {
        opening_balance: "100.00",
        closing_balance: "120.00",
        calculated_closing: "120.00",
        opening_delta: "0.00",
        closing_delta: "0.00",
        opening_match: true,
        closing_match: true,
        validated_at: "2024-01-31T00:00:00Z",
    },
    pdf_url: null,
    transactions: [
        {
            id: "txn-1",
            txn_date: "2024-01-03",
            description: "Salary",
            reference: "REF-1",
            amount: 20,
            direction: "IN",
            currency: "SGD",
            balance_after: 120,
            confidence: "high",
            status: "draft",
        },
    ],
    duplicate_candidates: [],
    transfer_pair_candidates: [],
};

describe("AC16.1.2 AC16.1.3 Statement review page", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("AC16.18.4 shows loading feedback while review data is pending", () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                return new Promise(() => undefined) as Promise<never>;
            }

            return Promise.resolve({ items: [{ id: "s1" }] });
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        expect(screen.getByText("Loading review data...")).toBeInTheDocument();
    });

    it("AC16.18.4 shows error fallback and retries the statement review fetch", async () => {
        let reviewAttempts = 0;

        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                reviewAttempts += 1;
                if (reviewAttempts === 1) {
                    return Promise.reject(new Error("network fail"));
                }

                return Promise.resolve(baseStatement);
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        expect(await screen.findByText("Failed to load statement")).toBeInTheDocument();
        expect(screen.getByText("network fail")).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: "Retry" }));

        expect(await screen.findByText("statement.pdf")).toBeInTheDocument();
        expect(reviewAttempts).toBe(2);
    });

    it("AC16.18.5 disables approve when balance validation fails", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve({
                    ...baseStatement,
                    balance_validation_result: {
                        ...baseStatement.balance_validation_result,
                        closing_match: false,
                    },
                });
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        const approveButton = await screen.findByRole("button", { name: "Approve" });
        expect(approveButton).toBeDisabled();
    });

    it("AC16.18.6 approves the statement and routes back to statement detail", async () => {
        mockedApi.mockImplementation((path: string, options?: RequestInit) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve(baseStatement);
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }

            if (path === "/api/statements/s1/review/approve") {
                expect(options).toMatchObject({ method: "POST" });
                return Promise.resolve({ journal_entries_created: 2 });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        fireEvent.click(await screen.findByRole("button", { name: "Approve" }));

        const dialog = await screen.findByRole("dialog", { name: "Approve Statement" });
        fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }));

        await waitFor(() => {
            expect(pushMock).toHaveBeenCalledWith("/statements/s1?approved=1&entriesCreated=2");
        });
    });

    it("AC16.18.6 rejects the statement with notes and routes back to statements", async () => {
        mockedApi.mockImplementation((path: string, options?: RequestInit) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve(baseStatement);
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }

            if (path === "/api/statements/s1/review/reject") {
                expect(options).toMatchObject({
                    method: "POST",
                    body: JSON.stringify({ notes: "Needs re-parse" }),
                });
                return Promise.resolve({ success: true });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        fireEvent.click(await screen.findByRole("button", { name: "Reject" }));

        const dialog = await screen.findByRole("dialog", { name: "Reject Statement" });
        fireEvent.change(within(dialog).getByRole("textbox"), {
            target: { value: "Needs re-parse" },
        });
        fireEvent.click(within(dialog).getByRole("button", { name: "Reject" }));

        await waitFor(() => {
            expect(pushMock).toHaveBeenCalledWith("/statements");
        });
    });

    it("AC16.18.6 lets reviewers move to adjacent pending statements", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve(baseStatement);
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({
                    items: [{ id: "s0" }, { id: "s1" }, { id: "s2" }],
                    total: 3,
                });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        fireEvent.click(await screen.findByRole("button", { name: "← Prev" }));
        fireEvent.click(screen.getByRole("button", { name: "Next →" }));

        expect(pushMock).toHaveBeenNthCalledWith(1, "/statements/s0/review");
        expect(pushMock).toHaveBeenNthCalledWith(2, "/statements/s2/review");
    });

    it("AC16.23.3 opens the conflict dialog when duplicate or transfer-pair candidates exist", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve({
                    ...baseStatement,
                    duplicate_candidates: [
                        {
                            description: "Duplicate salary",
                            txn_date: "2024-01-04",
                            amount: "20.00",
                        },
                    ],
                    transfer_pair_candidates: [
                        {
                            description: "Transfer to savings",
                            txn_date: "2024-01-05",
                            amount: "20.00",
                        },
                    ],
                });
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        const dialog = await screen.findByRole("dialog", { name: "Resolve Conflicts" });
        expect(within(dialog).getByText("Duplicate Candidates")).toBeInTheDocument();
        expect(within(dialog).getByText("Transfer Pair Candidates")).toBeInTheDocument();
    });
});
