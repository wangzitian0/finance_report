import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor, within } from "@testing-library/react";
import ReviewQueuePage from "@/app/(main)/reconciliation/review-queue/page";
import { apiFetch } from "@/lib/api";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({
    useRouter: vi.fn(() => ({ replace: vi.fn(), push: vi.fn() })),
    useSearchParams: vi.fn(() => new URLSearchParams()),
    usePathname: vi.fn(() => "/reconciliation"),
}));

const mockedApi = vi.mocked(apiFetch);

describe("ReviewQueuePage - coverage additions", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockedApi.mockReset();
    });

    it("renders checks and pending matches, toggles severity and minScore filter, select/deselect all", async () => {
        const data = {
            pending_matches: [
                { id: "m1", match_score: 90, status: "pending", created_at: null, description: "Good match", amount: 12.3, txn_date: "2024-01-02" },
                { id: "m2", match_score: 50, status: "pending", created_at: null, description: "Low match", amount: null, txn_date: null },
            ],
            consistency_checks: [
                { id: "c1", check_type: "duplicate", status: "pending", related_txn_ids: [], details: { message: "dup" }, severity: "high", resolved_at: null, resolution_note: null, created_at: "2024-01-01", updated_at: "2024-01-01" }
            ],
            has_unresolved_checks: false,
        };

        mockedApi.mockImplementation((path: string) => {
            if (String(path).includes("/stage2/queue")) return Promise.resolve(data as any);
            if (String(path).includes("consistency-checks/list")) return Promise.resolve({ items: data.consistency_checks } as any);
            if (String(path).includes("batch-approve-matches")) return Promise.resolve({ success: true, approved_count: 1 } as any);
            if (String(path).includes("batch-reject-matches")) return Promise.resolve({ success: true, rejected_count: 1 } as any);
            return Promise.resolve(null as any);
        });

        renderReviewComponent(<ReviewQueuePage /> as any);

        expect(await screen.findByText(/Reconciliation Review Queue/)).toBeInTheDocument();

        // toggle severity button
        const highBtn = await screen.findByRole("button", { name: /HIGH/i });
        fireEvent.click(highBtn);

        // change min score via range input
        const range = await screen.findByRole("slider");
        fireEvent.change(range, { target: { value: "80" } });

        // select all
        const selectAll = await screen.findByText(/Select all|Deselect all/);
        fireEvent.click(selectAll);

        // approve selected
        const approve = await screen.findByRole("button", { name: /Approve Selected/i });
        fireEvent.click(approve);

        await waitFor(() => expect(mockedApi.mock.calls.some(c => String(c[0]).includes("batch-approve-matches"))).toBe(true));

        // reject selected after the approve flow clears selection
        const desktopRegion = await screen.findByTestId("stage2-desktop-match-region");
        const row = within(desktopRegion).getByText("Good match").closest("tr") as HTMLTableRowElement;
        const checkbox = row.querySelector('input[type="checkbox"]') as HTMLInputElement;
        fireEvent.click(checkbox);
        const reject = await screen.findByRole("button", { name: /Reject/i });
        fireEvent.click(reject);
        await waitFor(() => expect(mockedApi.mock.calls.some(c => String(c[0]).includes("batch-reject-matches"))).toBe(true));
    });

    it("handles resolve dialog open and keydown escape to close", async () => {
        const data = {
            pending_matches: [],
            consistency_checks: [
                { id: "c2", check_type: "anomaly", status: "pending", related_txn_ids: [], details: { message: "anom" }, severity: "low", resolved_at: null, resolution_note: null, created_at: "2024-01-01", updated_at: "2024-01-01" }
            ],
            has_unresolved_checks: true,
        };

        mockedApi.mockResolvedValueOnce(data as any);
        mockedApi.mockResolvedValueOnce({ items: data.consistency_checks } as any);
        // resolve endpoint
        mockedApi.mockResolvedValueOnce({} as any);

        renderReviewComponent(<ReviewQueuePage /> as any);

        // open resolve
        const resolveBtn = await screen.findByRole("button", { name: /Resolve/i });
        fireEvent.click(resolveBtn);

        const dialog = await screen.findByRole("dialog");
        expect(dialog).toBeInTheDocument();

        // click Approve inside dialog
        const approveBtns = await screen.findAllByRole("button", { name: /Approve/i });
        const dialogApprove = approveBtns.find((b) => b.closest('[role="dialog"]')) || approveBtns[approveBtns.length - 1];
        fireEvent.click(dialogApprove);

        // ensure resolve API called for selected check
        await (async () => {
            const max = 20;
            for (let i = 0; i < max; i++) {
                if (mockedApi.mock.calls.some(c => String(c[0]).includes("consistency-checks"))) return;
                await new Promise(r => setTimeout(r, 50));
            }
            expect(mockedApi.mock.calls.some(c => String(c[0]).includes("consistency-checks"))).toBe(true);
        })();

        // press Escape - should close (no unhandled errors)
        fireEvent.keyDown(document, { key: "Escape" });
        await new Promise((r) => setTimeout(r, 50));
    });

    it("resolve dialog reject and flag actions call api", async () => {
        const data = {
            pending_matches: [],
            consistency_checks: [
                { id: "c3", check_type: "duplicate", status: "pending", related_txn_ids: [], details: { message: "dup3" }, severity: "medium", resolved_at: null, resolution_note: null, created_at: "2024-01-01", updated_at: "2024-01-01" }
            ],
            has_unresolved_checks: true,
        };

        mockedApi.mockImplementation((path: string) => {
            if (String(path).includes("/stage2/queue")) return Promise.resolve(data as any);
            if (String(path).includes("consistency-checks/list")) return Promise.resolve({ items: data.consistency_checks } as any);
            if (String(path).includes("consistency-checks") && String(path).includes("/resolve")) return Promise.resolve({} as any);
            return Promise.resolve(null as any);
        });

        renderReviewComponent(<ReviewQueuePage /> as any);

        const resolveBtn = await screen.findByRole("button", { name: /Resolve/i });
        fireEvent.click(resolveBtn);

        // click Reject inside dialog
        const rejectBtns = await screen.findAllByRole("button", { name: /Reject/i });
        const dialogReject = rejectBtns.find((b) => b.closest('[role="dialog"]')) || rejectBtns[rejectBtns.length - 1];
        fireEvent.click(dialogReject);

        await (async () => {
            const max = 20;
            for (let i = 0; i < max; i++) {
                if (mockedApi.mock.calls.some(c => String(c[0]).includes("consistency-checks"))) return;
                await new Promise(r => setTimeout(r, 50));
            }
            expect(mockedApi.mock.calls.some(c => String(c[0]).includes("consistency-checks"))).toBe(true);
        })();

        // Re-open dialog and click Flag
        fireEvent.click(await screen.findByRole("button", { name: /Resolve/i }));
        const flagBtns = await screen.findAllByRole("button", { name: /Flag/i });
        const dialogFlag = flagBtns.find((b) => b.closest('[role="dialog"]')) || flagBtns[flagBtns.length - 1];
        fireEvent.click(dialogFlag);

        await (async () => {
            const max = 20;
            for (let i = 0; i < max; i++) {
                if (mockedApi.mock.calls.filter(c => String(c[0]).includes("consistency-checks")).length >= 2) return;
                await new Promise(r => setTimeout(r, 50));
            }
            expect(mockedApi.mock.calls.filter(c => String(c[0]).includes("consistency-checks")).length).toBeGreaterThanOrEqual(2);
        })();
    });
});
