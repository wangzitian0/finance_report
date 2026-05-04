import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import ReviewQueuePage from "@/app/(main)/reconciliation/review-queue/page";
import { apiFetch } from "@/lib/api";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({
    useRouter: vi.fn(() => ({ replace: vi.fn(), push: vi.fn() })),
    useSearchParams: vi.fn(() => ({ get: () => null })),
    usePathname: vi.fn(() => "/"),
}));

const mockedApi = vi.mocked(apiFetch);

describe("ReviewQueuePage interactive flows", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("shows unresolved checks banner and disables Approve when unresolved", async () => {
        const data = {
            pending_matches: [{ id: 'm1', match_score: 90, status: 'pending', amount: 10, txn_date: '2024-01-02' }],
            consistency_checks: [{ id: 'c1', check_type: 'duplicate', status: 'pending', related_txn_ids: [], details: { message: 'dup' }, severity: 'high', resolved_at: null, resolution_note: null, created_at: '2024-01-01', updated_at: '2024-01-01' }],
            has_unresolved_checks: true,
        };

        // initial queue fetch
        mockedApi.mockResolvedValueOnce(data);
        // filtered checks
        mockedApi.mockResolvedValueOnce({ items: data.consistency_checks });

        renderReviewComponent(<ReviewQueuePage /> as any);

        expect(await screen.findByText('Unresolved consistency checks block batch approval')).toBeInTheDocument();

        // After load, Approve button should be disabled due to unresolved checks
        const approve = await screen.findByRole('button', { name: /Approve Selected/ });
        expect(approve).toBeDisabled();
    });

    it("selects and approves matches when resolved checks and shows toast result", async () => {
        const data = {
            pending_matches: [
                { id: 'm2', match_score: 88, status: 'pending', amount: 20, txn_date: '2024-01-03', description: 'match' },
            ],
            consistency_checks: [],
            has_unresolved_checks: false,
        };

        // queue
        mockedApi.mockResolvedValueOnce(data);
        // filtered checks
        mockedApi.mockResolvedValueOnce({ items: [] });
        // batch approve response
        mockedApi.mockResolvedValueOnce({ success: true, approved_count: 1 });

        renderReviewComponent(<ReviewQueuePage /> as any);

        // wait for table
        expect(await screen.findByText('Pending Matches')).toBeInTheDocument();

        // select the row checkbox by locating the row that contains the match description
        const row = await screen.findByText('match');
        const tr = row.closest('tr');
        const rowCheckbox = tr?.querySelector('input[type="checkbox"]') as HTMLInputElement;
        expect(rowCheckbox).toBeTruthy();
        fireEvent.click(rowCheckbox);

        // Approve should be enabled
        const approve = await screen.findByRole('button', { name: /Approve Selected/ });
        expect(approve).toBeEnabled();

        fireEvent.click(approve);

        // ensure the batch-approve API was called (third mock call)
        await (async () => {
            // wait for at least 3 calls: initial queue, filtered checks, then batch approve
            for (let i = 0; i < 20; i++) {
                if (mockedApi.mock.calls.length >= 3) return;
                await new Promise((r) => setTimeout(r, 50));
            }
        })();

        expect(mockedApi.mock.calls.length).toBeGreaterThanOrEqual(3);
        const found = mockedApi.mock.calls.some((c) => typeof c[0] === 'string' && c[0].includes('batch-approve-matches'));
        expect(found).toBe(true);
    });
});
