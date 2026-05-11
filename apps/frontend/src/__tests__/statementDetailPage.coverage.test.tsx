import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import StatementDetailPage from "@/app/(main)/statements/[id]/page";
import { apiFetch } from "@/lib/api";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("next/navigation", () => ({
    useParams: vi.fn(() => ({ id: "s1" })),
    useSearchParams: vi.fn(() => new URLSearchParams()),
}));

const mockedApi = vi.mocked(apiFetch);

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
});
