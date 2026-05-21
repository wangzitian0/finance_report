import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";

import ReviewPage from "@/app/(main)/review/page";
import { apiFetch } from "@/lib/api";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));

const mockedApi = vi.mocked(apiFetch);

describe("Review index page", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("AC16.11.32 shows pending stage 1 and stage 2 items through renderReviewComponent", async () => {
        mockedApi.mockResolvedValueOnce({
            items: [
                { id: "s1", original_filename: "Jan.pdf", institution: "DBS", confidence_score: 70, status: "parsed" },
            ],
            total: 1,
        });
        mockedApi.mockResolvedValueOnce({
            pending_matches: [
                { id: "m1", description: "Transfer", status: "pending_review", match_score: 82 },
                { id: "m2", description: "Ignored", status: "accepted", match_score: 90 },
            ],
        });

        renderReviewComponent(<ReviewPage />);

        expect(await screen.findByText("Review Queue")).toBeInTheDocument();
        expect(screen.getByText(/2 pending items/i)).toBeInTheDocument();
        expect(screen.getByText("Jan.pdf")).toBeInTheDocument();
        expect(screen.getByText("Transfer")).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /Open Stage 2 Review Queue/i })).toHaveAttribute("href", "/reconciliation/review-queue");
    });

    it("shows loading state before data resolves", async () => {
        let resolveStage1: ((value: unknown) => void) | undefined;
        const stage1Promise = new Promise((resolve) => {
            resolveStage1 = resolve;
        });

        mockedApi.mockImplementationOnce(() => stage1Promise as Promise<any>);
        mockedApi.mockResolvedValueOnce({ pending_matches: [] });

        renderReviewComponent(<ReviewPage />);
        expect(screen.getByText("Loading review queue...")).toBeInTheDocument();

        resolveStage1?.({ items: [], total: 0 });
        expect(await screen.findByText("Review Queue")).toBeInTheDocument();
    });

    it("shows error when queue fetch fails", async () => {
        mockedApi.mockRejectedValueOnce(new Error("boom"));

        renderReviewComponent(<ReviewPage />);

        expect(await screen.findByText("Review Queue")).toBeInTheDocument();
        expect(screen.getByText("boom")).toBeInTheDocument();
    });
});
