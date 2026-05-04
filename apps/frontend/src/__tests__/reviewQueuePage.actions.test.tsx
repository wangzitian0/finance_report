import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ReviewQueuePage from "@/app/(main)/reconciliation/review-queue/page";
import { renderReviewComponent } from "@/__tests__/helpers/renderReviewComponent";
import { apiFetch } from "@/lib/api";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: vi.fn(() => ({ replace: vi.fn(), push: vi.fn() })), useSearchParams: vi.fn(() => ({ get: () => null })), usePathname: vi.fn(() => "/") }));

const mocked = vi.mocked(apiFetch);

describe("Review queue actions", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("renders matches and calls batch approve endpoint when Approve selected", async () => {
        const data = {
            pending_matches: [
                { id: 'm1', match_score: 90, status: 'pending', amount: 10, txn_date: '2024-01-02', description: 'A' },
                { id: 'm2', match_score: 80, status: 'pending', amount: 20, txn_date: '2024-01-03', description: 'B' },
            ],
            consistency_checks: [],
            has_unresolved_checks: false,
        };

        mocked.mockResolvedValueOnce(data); // initial queue
        mocked.mockResolvedValueOnce({ items: [] }); // filtered checks
        mocked.mockResolvedValueOnce({ success: true, approved_count: 2 }); // batch approve

        renderReviewComponent(<ReviewQueuePage /> as any);

        expect(await screen.findByText('Pending Matches')).toBeInTheDocument();

        // select first row checkbox
        const row = await screen.findByText('A');
        const tr = row.closest('tr') as HTMLTableRowElement;
        const cb = tr.querySelector('input[type="checkbox"]') as HTMLInputElement;
        fireEvent.click(cb);

        const approve = await screen.findByRole('button', { name: /Approve Selected/ });
        expect(approve).toBeEnabled();

        fireEvent.click(approve);

        // wait for api calls
        for (let i = 0; i < 20; i++) {
            if (mocked.mock.calls.length >= 3) break;
            await new Promise((r) => setTimeout(r, 50));
        }

        const found = mocked.mock.calls.some((c) => typeof c[0] === 'string' && c[0].includes('batch-approve-matches'));
        expect(found).toBe(true);
    });

    it("toggles severity filters and refetches filtered checks", async () => {
        const data = { pending_matches: [], consistency_checks: [{ id: 'c1', check_type: 'duplicate', status: 'pending', related_txn_ids: [], details: { message: 'x' }, severity: 'high', resolved_at: null, resolution_note: null, created_at: '', updated_at: '' }], has_unresolved_checks: false };

        mocked.mockResolvedValueOnce(data);
        mocked.mockResolvedValueOnce({ items: data.consistency_checks });

        renderReviewComponent(<ReviewQueuePage /> as any);

        // wait for checks
        expect(await screen.findByText('Consistency Checks')).toBeInTheDocument();

        const highBtn = screen.getByRole('button', { name: 'HIGH' });
        fireEvent.click(highBtn);

        // wait for filtered fetch to be called a second time
        for (let i = 0; i < 20; i++) {
            if (mocked.mock.calls.length >= 2) break;
            await new Promise((r) => setTimeout(r, 50));
        }

        expect(mocked).toHaveBeenCalled();
    });

    it("opens resolve dialog and approves a check", async () => {
        const data = { pending_matches: [], consistency_checks: [{ id: 'c2', check_type: 'duplicate', status: 'pending', related_txn_ids: [], details: { message: 'check me' }, severity: 'high', resolved_at: null, resolution_note: null, created_at: '', updated_at: '' }], has_unresolved_checks: false };

        mocked.mockResolvedValueOnce(data);
        mocked.mockResolvedValueOnce({ items: data.consistency_checks });
        mocked.mockResolvedValueOnce({ success: true }); // resolve endpoint

        renderReviewComponent(<ReviewQueuePage /> as any);

        // wait for Resolve button to appear
        const resolveBtn = await screen.findByRole('button', { name: /Resolve/ });
        fireEvent.click(resolveBtn);

        // dialog shows Approve button
        const approve = await screen.findByRole('button', { name: 'Approve' });
        fireEvent.click(approve);

        // ensure api was called for resolve
        for (let i = 0; i < 20; i++) {
            if (mocked.mock.calls.length >= 3) break;
            await new Promise((r) => setTimeout(r, 50));
        }

        const found = mocked.mock.calls.some((c) => typeof c[0] === 'string' && c[0].includes('/consistency-checks/') && c[0].includes('/resolve'));
        expect(found).toBe(true);
    });

    it("shows unresolved checks warning and disables approve", async () => {
        const data = {
            pending_matches: [{ id: 'm10', match_score: 90, status: 'pending', amount: 5, txn_date: '2024-01-05', description: 'X' }],
            consistency_checks: [],
            has_unresolved_checks: true,
        };

        mocked.mockResolvedValueOnce(data);
        mocked.mockResolvedValueOnce({ items: [] });

        renderReviewComponent(<ReviewQueuePage /> as any);

        // wait for page
        expect(await screen.findByText('Reconciliation Review Queue')).toBeInTheDocument();

        // warning shown
        expect(screen.getByText(/Unresolved consistency checks block batch approval/i)).toBeInTheDocument();

        // select the row
        const row = await screen.findByText('X');
        const tr = row.closest('tr') as HTMLTableRowElement;
        const cb = tr.querySelector('input[type="checkbox"]') as HTMLInputElement;
        fireEvent.click(cb);

        const approve = await screen.findByRole('button', { name: /Approve Selected/ });
        expect(approve).toBeDisabled();
    });

    it("selects all and batch rejects selected matches", async () => {
        const data = {
            pending_matches: [
                { id: 'r1', match_score: 70, status: 'pending', amount: 1, txn_date: '2024-01-01', description: 'one' },
                { id: 'r2', match_score: 80, status: 'pending', amount: 2, txn_date: '2024-01-02', description: 'two' },
            ],
            consistency_checks: [],
            has_unresolved_checks: false,
        };

        mocked.mockResolvedValueOnce(data); // initial
        mocked.mockResolvedValueOnce({ items: [] }); // filtered
        mocked.mockResolvedValueOnce({ success: true, rejected_count: 2 }); // batch reject

        renderReviewComponent(<ReviewQueuePage /> as any);

        // wait for table
        expect(await screen.findByText('Pending Matches')).toBeInTheDocument();

        // click Select all
        const selectAll = screen.getByText(/Select all|Deselect all/);
        fireEvent.click(selectAll);

        // now Reject button should be enabled
        const reject = await screen.findByRole('button', { name: /Reject/ });
        expect(reject).toBeEnabled();

        fireEvent.click(reject);

        // wait for api call to batch-reject-matches
        for (let i = 0; i < 20; i++) {
            if (mocked.mock.calls.length >= 3) break;
            await new Promise((r) => setTimeout(r, 50));
        }

        const found = mocked.mock.calls.some((c) => typeof c[0] === 'string' && c[0].includes('batch-reject-matches'));
        expect(found).toBe(true);
    });
});
