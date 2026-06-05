import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import ReviewQueuePage from "@/app/(main)/reconciliation/review-queue/page";
import { apiFetch } from "@/lib/api";

import { renderReviewComponent } from "./helpers/renderReviewComponent";

const replaceMock = vi.fn();
const pushMock = vi.fn();

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({
    useRouter: vi.fn(() => ({ replace: replaceMock, push: pushMock })),
    useSearchParams: vi.fn(() => new URLSearchParams()),
    usePathname: vi.fn(() => "/reconciliation/review-queue"),
}));

const mockedApi = vi.mocked(apiFetch);

const queueData = {
    pending_matches: [
        {
            id: "m1",
            match_score: 88,
            status: "pending_review",
            created_at: "2024-01-03T00:00:00Z",
            description: "Transfer",
            amount: 20,
            txn_date: "2024-01-03",
        },
    ],
    consistency_checks: [],
    has_unresolved_checks: false,
};

const duplicateCheck = {
    id: "c1",
    check_type: "duplicate",
    status: "pending",
    related_txn_ids: [],
    details: { message: "Duplicate transfer" },
    severity: "high",
    resolved_at: null,
    resolution_note: null,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
};

describe("AC4.6.4 ReviewQueuePage interactive flows", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("AC16.17.1 shows loading feedback while the Stage 2 queue is pending", () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/stage2/queue") {
                return new Promise(() => undefined) as Promise<never>;
            }

            return Promise.resolve({ items: [] });
        });

        renderReviewComponent(<ReviewQueuePage /> as never);

        expect(screen.getByText("Loading review queue...")).toBeInTheDocument();
    });

    it("AC16.17.1 shows an error fallback and retries the Stage 2 queue fetch", async () => {
        let queueAttempts = 0;

        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/stage2/queue") {
                queueAttempts += 1;
                if (queueAttempts === 1) {
                    return Promise.reject(new Error("queue exploded"));
                }

                return Promise.resolve(queueData);
            }

            if (path.startsWith("/api/statements/consistency-checks/list")) {
                return Promise.resolve({ items: [] });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<ReviewQueuePage /> as never);

        expect(await screen.findByText("Failed to load review queue")).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: "Retry" }));

        expect(await screen.findByText("Pending Matches")).toBeInTheDocument();
        expect(queueAttempts).toBe(2);
    });

    it("AC16.17.2 renders empty states when no checks or matches remain", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/stage2/queue") {
                return Promise.resolve({
                    pending_matches: [],
                    consistency_checks: [],
                    has_unresolved_checks: false,
                });
            }

            if (path.startsWith("/api/statements/consistency-checks/list")) {
                return Promise.resolve({ items: [] });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<ReviewQueuePage /> as never);

        expect(await screen.findByText("No pending checks")).toBeInTheDocument();
        expect(screen.getByText("No pending matches")).toBeInTheDocument();
    });

    it("AC16.2.3/AC16.17.2 disables batch approval while unresolved checks remain", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/stage2/queue") {
                return Promise.resolve({
                    pending_matches: queueData.pending_matches,
                    consistency_checks: [duplicateCheck],
                    has_unresolved_checks: true,
                });
            }

            if (path.startsWith("/api/statements/consistency-checks/list")) {
                return Promise.resolve({ items: [duplicateCheck] });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<ReviewQueuePage /> as never);

        expect(await screen.findByText("Unresolved consistency checks block batch approval")).toBeInTheDocument();

        const approveButton = screen.getByRole("button", { name: /Approve Selected/i });
        expect(approveButton).toBeDisabled();
    });

    it("AC16.32.3 requests an expanded consistency-check limit for unblockable queues", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/stage2/queue") {
                return Promise.resolve({
                    pending_matches: [],
                    consistency_checks: [],
                    has_unresolved_checks: false,
                });
            }

            if (path.startsWith("/api/statements/consistency-checks/list")) {
                expect(path).toContain("limit=500");
                return Promise.resolve({ items: [] });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<ReviewQueuePage /> as never);

        expect(await screen.findByText("No pending checks")).toBeInTheDocument();
    });

    it("AC16.2.4/AC16.17.3 approves selected matches through the batch approval API", async () => {
        mockedApi.mockImplementation((path: string, options?: RequestInit) => {
            if (path === "/api/statements/stage2/queue") {
                return Promise.resolve(queueData);
            }

            if (path.startsWith("/api/statements/consistency-checks/list")) {
                return Promise.resolve({ items: [] });
            }

            if (path === "/api/statements/batch-approve-matches") {
                expect(options).toMatchObject({
                    method: "POST",
                    body: JSON.stringify({ match_ids: ["m1"] }),
                });
                return Promise.resolve({ success: true, approved_count: 1 });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<ReviewQueuePage /> as never);

        const desktopRegion = await screen.findByTestId("stage2-desktop-match-region");
        fireEvent.click(within(desktopRegion).getByText("Transfer"));
        fireEvent.click(screen.getByRole("button", { name: /Approve Selected/i }));

        await waitFor(() => {
            expect(mockedApi).toHaveBeenCalledWith(
                "/api/statements/batch-approve-matches",
                expect.objectContaining({
                    method: "POST",
                    body: JSON.stringify({ match_ids: ["m1"] }),
                }),
            );
        });
    });

    it("AC16.17.3 rejects selected matches through the batch rejection API", async () => {
        mockedApi.mockImplementation((path: string, options?: RequestInit) => {
            if (path === "/api/statements/stage2/queue") {
                return Promise.resolve(queueData);
            }

            if (path.startsWith("/api/statements/consistency-checks/list")) {
                return Promise.resolve({ items: [] });
            }

            if (path === "/api/statements/batch-reject-matches") {
                expect(options).toMatchObject({
                    method: "POST",
                    body: JSON.stringify({ match_ids: ["m1"] }),
                });
                return Promise.resolve({ success: true, rejected_count: 1 });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<ReviewQueuePage /> as never);

        const desktopRegion = await screen.findByTestId("stage2-desktop-match-region");
        fireEvent.click(within(desktopRegion).getByText("Transfer"));
        fireEvent.click(screen.getByRole("button", { name: "Reject" }));

        await waitFor(() => {
            expect(mockedApi).toHaveBeenCalledWith(
                "/api/statements/batch-reject-matches",
                expect.objectContaining({
                    method: "POST",
                    body: JSON.stringify({ match_ids: ["m1"] }),
                }),
            );
        });
    });

    it("AC16.17.4 resolves a consistency check from the dialog actions", async () => {
        mockedApi.mockImplementation((path: string, options?: RequestInit) => {
            if (path === "/api/statements/stage2/queue") {
                return Promise.resolve({
                    pending_matches: [],
                    consistency_checks: [duplicateCheck],
                    has_unresolved_checks: true,
                });
            }

            if (path.startsWith("/api/statements/consistency-checks/list")) {
                return Promise.resolve({ items: [duplicateCheck] });
            }

            if (path === "/api/statements/consistency-checks/c1/resolve") {
                expect(options).toMatchObject({
                    method: "POST",
                    body: JSON.stringify({ action: "approve", note: "Looks good" }),
                });
                return Promise.resolve({ success: true });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<ReviewQueuePage /> as never);

        fireEvent.click(await screen.findByRole("button", { name: "Resolve" }));

        const dialog = await screen.findByRole("dialog", { name: "Resolve Consistency Check" });
        fireEvent.change(within(dialog).getByRole("textbox"), {
            target: { value: "Looks good" },
        });
        fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }));

        await waitFor(() => {
            expect(mockedApi).toHaveBeenCalledWith(
                "/api/statements/consistency-checks/c1/resolve",
                expect.objectContaining({
                    method: "POST",
                    body: JSON.stringify({ action: "approve", note: "Looks good" }),
                }),
            );
        });
    });
});
