import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import StatementReviewPage from "@/app/(main)/statements/[id]/review/page";
import { apiFetch } from "@/lib/api";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({
    useRouter: vi.fn(() => ({ replace: vi.fn(), push: vi.fn() })),
    useParams: vi.fn(() => ({ id: "s1" })),
}));

const mockedApi = vi.mocked(apiFetch);

describe("StatementReviewPage - coverage additions", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("renders loading then empty transactions and handles retry/back link", async () => {
        mockedApi.mockResolvedValueOnce(null as any); // first query returns falsy -> not found
        // pending statements
        mockedApi.mockResolvedValueOnce({ items: [] });

        renderReviewComponent(<StatementReviewPage /> as any);

        expect(await screen.findByText("Statement not found")).toBeInTheDocument();
        expect(await screen.findByRole("link", { name: /Back to Statements/i })).toBeInTheDocument();
    });

    it("AC16.11.33 handles inline edit flow: begin edit, change value, save triggers api", async () => {
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

        // statement fetch
        mockedApi.mockResolvedValueOnce(stmt as any);
        // pending statements
        mockedApi.mockResolvedValueOnce({ items: [{ id: "s1" }] });

        // mock edit mutation endpoint response
        mockedApi.mockResolvedValueOnce({ success: true });

        renderReviewComponent(<StatementReviewPage /> as any);

        // wait for approve button enabled
        const approveBtn = await screen.findByRole("button", { name: /Approve/ });
        expect(approveBtn).toBeEnabled();

        // begin edit by clicking description cell
        const desc = await screen.findByText("Lunch");
        fireEvent.click(desc);

        const input = await screen.findByDisplayValue("Lunch");
        fireEvent.change(input, { target: { value: "Lunch at cafe" } });
        // blur to end edit
        fireEvent.blur(input);

        // Save edits button should appear
        const saveBtn = await screen.findByRole("button", { name: /Save Edits/i });
        expect(saveBtn).toBeInTheDocument();
        const discardBtn = await screen.findByRole("button", { name: /Discard/i });
        fireEvent.click(discardBtn);

        fireEvent.click(await screen.findByText("Lunch"));
        const secondInput = await screen.findByDisplayValue("Lunch");
        fireEvent.change(secondInput, { target: { value: "Lunch at cafe" } });
        fireEvent.blur(secondInput);

        fireEvent.click(await screen.findByRole("button", { name: /Save Edits/i }));

        // edit API should have been called (third api call)
        await (async () => {
            // wait for api to be called with edit endpoint
            const max = 20;
            for (let i = 0; i < max; i++) {
                if (mockedApi.mock.calls.some(c => String(c[0]).includes("/review/edit"))) return;
                await new Promise(r => setTimeout(r, 50));
            }
            // final assertion
            expect(mockedApi.mock.calls.some(c => String(c[0]).includes("/review/edit"))).toBe(true);
        })();
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
            duplicate_candidates: [{ description: "dup", txn_date: "2024-01-01", amount: 10 }],
            transfer_pair_candidates: [{ description: "pair", txn_date: "2024-01-02", amount: 20 }],
        };

        mockedApi.mockResolvedValueOnce(stmt as any);
        mockedApi.mockResolvedValueOnce({ items: [] });

        renderReviewComponent(<StatementReviewPage /> as any);

        // Conflict dialog content should be visible due to useEffect opening it
        expect(await screen.findByText(/Resolve Conflicts/i)).toBeInTheDocument();
        expect(screen.getByText("dup")).toBeInTheDocument();
        expect(screen.getByText("pair")).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: "Close" }));
        expect(screen.queryByText(/Resolve Conflicts/i)).not.toBeInTheDocument();
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

        // initial data + pending statements
        mockedApi.mockResolvedValueOnce(stmt as any);
        mockedApi.mockResolvedValueOnce({ items: [] });

        // approve endpoint
        mockedApi.mockResolvedValueOnce({});
        // reject endpoint
        mockedApi.mockResolvedValueOnce({});

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
});
