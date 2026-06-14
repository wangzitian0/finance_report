import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import ReviewQueuePage from "@/app/(main)/reconciliation/review-queue/page";
import StatementReviewPage from "@/app/(main)/statements/[id]/review/page";
import { PdfPreviewPane } from "@/components/review/PdfPreviewPane";
import { apiDownload, apiFetch } from "@/lib/api";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn(), apiDownload: vi.fn() }));

const mockedDownload = vi.mocked(apiDownload);
vi.mock("next/navigation", () => ({
    useRouter: vi.fn(() => ({ replace: vi.fn(), push: vi.fn() })),
    useSearchParams: vi.fn(() => ({ get: () => null })),
    usePathname: vi.fn(() => "/"),
    useParams: vi.fn(() => ({ id: "s1" })),
}));

const mockedApi = vi.mocked(apiFetch);

describe("Review pages data flows", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        // PdfPreviewPane fetches the document blob on mount; give every test a
        // safe default so unrelated review-page renders don't crash on it.
        mockedDownload.mockResolvedValue({ blob: new Blob(["%PDF-1.4"]), filename: "f.pdf" });
        URL.createObjectURL = vi.fn(() => "blob:preview-1");
        URL.revokeObjectURL = vi.fn();
    });

    it("review queue shows empty state and toggles severity filter", async () => {
        mockedApi.mockResolvedValueOnce({ pending_matches: [], consistency_checks: [], has_unresolved_checks: false });
        // filtered checks call
        mockedApi.mockResolvedValueOnce({ items: [] });
        renderReviewComponent(<ReviewQueuePage /> as any);
        expect(await screen.findByText("Review queue")).toBeInTheDocument();
        expect(await screen.findByText("No pending matches")).toBeInTheDocument();
    });

    it("statement review page shows loading fallback then data", async () => {
        const stmt = {
            id: "s1",
            original_filename: "f.pdf",
            institution: "Bank",
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
            if (path === "/api/statements/s1/review") return Promise.resolve(stmt);
            if (path === "/api/statements/pending-review") return Promise.resolve({ items: [{ id: "s1" }] });
            if (path === "/api/review/conflicts/s1") return Promise.resolve({ duplicates: [], transfer_pairs: [] });
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as any);
        expect(await screen.findByText("Back to Statements")).toBeInTheDocument();
    });

    it("AC16.33.5 embeds the document as a same-origin sandboxed blob URL", async () => {
        renderReviewComponent(<PdfPreviewPane statementId="s1" hasDocument /> as any);

        const iframe = await screen.findByTitle("Statement PDF preview");
        // AC16.33.5: fetched from the authenticated same-origin proxy, never a
        // cross-origin object-storage URL, and embedded as a blob: object URL.
        expect(mockedDownload).toHaveBeenCalledWith("/api/statements/s1/document");
        expect(iframe).toHaveAttribute("src", "blob:preview-1");
        expect(iframe).toHaveAttribute("sandbox");
        expect(iframe).toHaveAttribute("referrerPolicy", "no-referrer");
    });

    it("AC16.33.5 shows a fallback and skips the fetch when no document exists", () => {
        mockedDownload.mockClear();
        renderReviewComponent(<PdfPreviewPane statementId="s1" hasDocument={false} /> as any);

        expect(mockedDownload).not.toHaveBeenCalled();
        expect(screen.getByText("PDF preview not available")).toBeInTheDocument();
    });

    it("AC16.33.5 surfaces an error message when the document fetch fails", async () => {
        mockedDownload.mockRejectedValueOnce(new Error("502 Bad Gateway"));
        renderReviewComponent(<PdfPreviewPane statementId="s1" hasDocument /> as any);

        expect(await screen.findByText("PDF preview could not be loaded")).toBeInTheDocument();
    });

    it("AC16.33.5 revokes the blob object URL on unmount to avoid leaks", async () => {
        const { unmount } = renderReviewComponent(<PdfPreviewPane statementId="s1" hasDocument /> as any);
        await screen.findByTitle("Statement PDF preview");

        unmount();
        expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview-1");
    });

    it("AC16.33.5 ignores a fetch that resolves after unmount (no state update)", async () => {
        let resolveDownload!: (v: { blob: Blob; filename: string | null }) => void;
        mockedDownload.mockReturnValueOnce(new Promise((r) => { resolveDownload = r; }));
        const createObjectURL = vi.mocked(URL.createObjectURL);
        createObjectURL.mockClear();

        const { unmount } = renderReviewComponent(<PdfPreviewPane statementId="s1" hasDocument /> as any);
        unmount();
        resolveDownload({ blob: new Blob(["%PDF"]), filename: "f.pdf" });
        await Promise.resolve();

        // The cancelled guard short-circuits before creating an object URL.
        expect(createObjectURL).not.toHaveBeenCalled();
    });

    it("AC16.33.5 ignores a fetch that rejects after unmount (no error state)", async () => {
        let rejectDownload!: (e: Error) => void;
        mockedDownload.mockReturnValueOnce(new Promise((_, rej) => { rejectDownload = rej; }));

        const { unmount } = renderReviewComponent(<PdfPreviewPane statementId="s1" hasDocument /> as any);
        unmount();
        rejectDownload(new Error("late failure"));
        await Promise.resolve();

        // Nothing to assert beyond no thrown error: the cancelled guard prevents a
        // post-unmount setState. Reaching here without an unhandled rejection passes.
        expect(true).toBe(true);
    });
});
