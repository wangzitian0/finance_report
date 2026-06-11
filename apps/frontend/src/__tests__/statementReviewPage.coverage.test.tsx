import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor, within } from "@testing-library/react";
import StatementReviewPage from "@/app/(main)/statements/[id]/review/page";
import { apiFetch } from "@/lib/api";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({
    useRouter: vi.fn(() => ({ replace: vi.fn(), push: vi.fn() })),
    useParams: vi.fn(() => ({ id: "s1" })),
}));

const mockedApi = vi.mocked(apiFetch);
const emptyConflicts = { duplicates: [], transfer_pairs: [] };

describe("StatementReviewPage - coverage additions", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("renders loading then empty transactions and handles retry/back link", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") return Promise.resolve(null as any);
            if (path === "/api/statements/pending-review") return Promise.resolve({ items: [] });
            if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as any);

        expect(await screen.findByText("Statement not found")).toBeInTheDocument();
        expect(await screen.findByRole("link", { name: /Back to Statements/i })).toBeInTheDocument();
    });

    it("renders parsed transactions read-only with no inline-edit or approve-edits affordance", async () => {
        const stmt = {
            id: "s1",
            original_filename: "file.pdf",
            institution: "BankX",
            currency: "SGD",
            period_start: "2024-01-01",
            period_end: "2024-01-31",
            opening_balance: 100,
            closing_balance: 200,
            status: "pending",
            stage1_status: null,
            balance_validation_result: { opening_match: true, closing_match: true, calculated_closing: "200" },
            pdf_url: null,
            transactions: [
                { id: "t1", txn_date: "2024-01-02", description: "Lunch", amount: 12.5, direction: "OUT", currency: "SGD", confidence: "medium" },
                { id: "t2", txn_date: "2024-01-03", description: "Salary", amount: 1000, direction: "IN", currency: "SGD", confidence: "high" },
            ],
        };

        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") return Promise.resolve(stmt as any);
            if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }] });
            if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as any);

        // wait for approve button enabled (as-is parse approval still exists)
        const approveBtn = await screen.findByRole("button", { name: /Approve/ });
        expect(approveBtn).toBeEnabled();

        // Transactions render as static text; clicking does not open any inline editor.
        const desktopRegion = await screen.findByTestId("stage1-desktop-transaction-region");
        const desktopTransactions = within(desktopRegion);
        fireEvent.click(desktopTransactions.getByText("Lunch"));
        expect(desktopTransactions.queryByDisplayValue("Lunch")).toBeNull();

        // The dead "Approve Edits" path must be gone.
        expect(screen.queryByRole("button", { name: /Approve Edits/i })).toBeNull();
        expect(screen.queryByRole("button", { name: /Discard/i })).toBeNull();

        // The edit endpoint must never be called.
        expect(mockedApi.mock.calls.some((c) => String(c[0]).includes("/review/edit"))).toBe(false);
    });

    it("opens conflict dialog when duplicate/transfer candidates present", async () => {
        const stmt = {
            id: "s1",
            original_filename: "file.pdf",
            institution: "BankX",
            currency: "SGD",
            period_start: null,
            period_end: null,
            opening_balance: null,
            closing_balance: null,
            status: "pending",
            stage1_status: null,
            balance_validation_result: null,
            pdf_url: null,
            transactions: [],
        };

        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") return Promise.resolve(stmt as any);
            if (path === "/api/statements/pending-review") return Promise.resolve({ items: [] });
            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve({
                    duplicates: [{ description: "dup", txn_date: "2024-01-01", amount: 10 }],
                    transfer_pairs: [{ description: "pair", txn_date: "2024-01-02", amount: 20 }],
                });
            }
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as any);

        // Conflict dialog content should be visible due to useEffect opening it
        expect(await screen.findByRole("dialog", { name: "Resolve Conflicts" })).toBeInTheDocument();
        expect(screen.getByText("dup")).toBeInTheDocument();
        expect(screen.getByText("pair")).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: "Close" }));
        expect(screen.queryByRole("dialog", { name: "Resolve Conflicts" })).not.toBeInTheDocument();
    });

    it("handles approve/reject confirm dialogs and API calls", async () => {
        const stmt = {
            id: "s1",
            original_filename: "file.pdf",
            institution: "BankX",
            currency: "SGD",
            period_start: "2024-01-01",
            period_end: "2024-01-31",
            opening_balance: 0,
            closing_balance: 0,
            status: "pending",
            stage1_status: null,
            balance_validation_result: { opening_match: true, closing_match: true, calculated_closing: "0" },
            pdf_url: null,
            transactions: [],
        };

        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") return Promise.resolve(stmt as any);
            if (path === "/api/statements/pending-review") return Promise.resolve({ items: [] });
            if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
            if (path === "/api/statements/s1/review/approve") return Promise.resolve({});
            if (path === "/api/statements/s1/review/reject") return Promise.resolve({});
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as any);

        const approveBtn = await screen.findByRole("button", { name: "Approve" });
        fireEvent.click(approveBtn);

        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
        fireEvent.click(approveBtn);

        // dialog confirm - pick the Approve button inside the dialog
        const approveBtns = await screen.findAllByRole("button", { name: "Approve" });
        const dialogApprove = approveBtns.find((b) => b.closest('[role="dialog"]')) || approveBtns[approveBtns.length - 1];
        fireEvent.click(dialogApprove);

        // ensure approve API called
        await (async () => {
            const max = 20;
            for (let i = 0; i < max; i++) {
                if (mockedApi.mock.calls.some(c => String(c[0]).includes("/review/approve"))) return;
                await new Promise(r => setTimeout(r, 50));
            }
            expect(mockedApi.mock.calls.some(c => String(c[0]).includes("/review/approve"))).toBe(true);
        })();
        const approveCall = mockedApi.mock.calls.find(c => String(c[0]).includes("/review/approve"));
        expect(approveCall?.[1]).toMatchObject({
            method: "POST",
            body: JSON.stringify({ create_account_if_missing: true }),
        });

        // Now test reject
        const rejectBtn = await screen.findByRole("button", { name: "Reject" });
        fireEvent.click(rejectBtn);

        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
        fireEvent.click(rejectBtn);

        const rejectBtns = await screen.findAllByRole("button", { name: "Reject" });
        const dialogReject = rejectBtns.find((b) => b.closest('[role="dialog"]')) || rejectBtns[rejectBtns.length - 1];
        fireEvent.click(dialogReject);

        await (async () => {
            const max = 20;
            for (let i = 0; i < max; i++) {
                if (mockedApi.mock.calls.some(c => String(c[0]).includes("/review/reject"))) return;
                await new Promise(r => setTimeout(r, 50));
            }
            expect(mockedApi.mock.calls.some(c => String(c[0]).includes("/review/reject"))).toBe(true);
        })();
    });

    it("test_AC8_13_48 surfaces approve and reject mutation failures", async () => {
        const stmt = {
            id: "s1",
            original_filename: "file.pdf",
            institution: "BankX",
            currency: "SGD",
            period_start: "2024-01-01",
            period_end: "2024-01-31",
            opening_balance: 0,
            closing_balance: 0,
            status: "pending",
            stage1_status: null,
            balance_validation_result: { opening_match: true, closing_match: true, calculated_closing: "0" },
            pdf_url: null,
            transactions: [],
        };

        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") return Promise.resolve(stmt as any);
            if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }] });
            if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
            if (path === "/api/statements/s1/review/approve") return Promise.reject(new Error("approve failed"));
            if (path === "/api/statements/s1/review/reject") return Promise.reject(new Error("reject failed"));
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as any);

        fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
        const approveDialog = await screen.findByRole("dialog", { name: "Approve Statement" });
        fireEvent.click(within(approveDialog).getByRole("button", { name: "Approve" }));
        expect(await screen.findByText("approve failed")).toBeInTheDocument();
        fireEvent.click(within(approveDialog).getByRole("button", { name: "Cancel" }));

        fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
        const rejectDialog = await screen.findByRole("dialog", { name: "Reject Statement" });
        fireEvent.click(within(rejectDialog).getByRole("button", { name: "Reject" }));
        expect(await screen.findByText("reject failed")).toBeInTheDocument();
    });

    // AC22.5.2: a balance-validation block surfaces an in-place "Re-parse statement"
    // action that hits the retry endpoint without leaving the review page.
    it("AC22.5.2 re-parses in place when balance validation blocks approval", async () => {
        const stmt = {
            id: "s1",
            original_filename: "file.pdf",
            institution: "BankX",
            currency: "SGD",
            period_start: "2024-01-01",
            period_end: "2024-01-31",
            opening_balance: 100,
            closing_balance: 200,
            status: "pending",
            stage1_status: null,
            balance_validation_result: { opening_match: false, closing_match: false, calculated_closing: "150" },
            pdf_url: null,
            transactions: [],
        };

        const retryResolved = vi.fn();
        mockedApi.mockImplementation((path: string, init?: any) => {
            if (path === "/api/statements/s1/review") return Promise.resolve(stmt as any);
            if (path === "/api/statements/pending-review") return Promise.resolve({ items: [] });
            if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
            if (path === "/api/statements/s1/retry") {
                retryResolved(init?.method);
                return Promise.resolve({});
            }
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as any);

        // Approve is blocked with a plain-language reason instead of a bare tooltip.
        expect(await screen.findByText(/closing balance doesn't match/i)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();

        fireEvent.click(screen.getByRole("button", { name: /Re-parse statement/i }));

        await waitFor(() => expect(retryResolved).toHaveBeenCalledWith("POST"));
    });

    it("AC22.5.2 surfaces an error when in-place re-parse fails", async () => {
        const stmt = {
            id: "s1",
            original_filename: "file.pdf",
            institution: "BankX",
            currency: "SGD",
            period_start: "2024-01-01",
            period_end: "2024-01-31",
            opening_balance: 100,
            closing_balance: 200,
            status: "pending",
            stage1_status: null,
            balance_validation_result: { opening_match: false, closing_match: false, calculated_closing: "150" },
            pdf_url: null,
            transactions: [],
        };

        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") return Promise.resolve(stmt as any);
            if (path === "/api/statements/pending-review") return Promise.resolve({ items: [] });
            if (path === "/api/review/conflicts/s1") return Promise.resolve(emptyConflicts);
            if (path === "/api/statements/s1/retry") return Promise.reject(new Error("re-parse failed"));
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as any);

        fireEvent.click(await screen.findByRole("button", { name: /Re-parse statement/i }));
        expect(await screen.findByText("re-parse failed")).toBeInTheDocument();
    });
});
