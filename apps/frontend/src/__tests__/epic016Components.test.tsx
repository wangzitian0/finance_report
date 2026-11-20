import { screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderReviewComponent as rc } from "./helpers/renderReviewComponent";
import { ConflictResolutionDialog, PdfPreviewPane, TransactionTable } from "@/components/statements/StatementReview";
import { BottomTabBar } from "@/components/AppShell";
vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard", useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
const dl = vi.fn(), S = screen, E = expect;
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn(), apiOperationDownload: (...a: unknown[]) => dl(...a) }));
it("AC16.23.6 AC16.33.5 EPIC-016 components", async () => {
const r0 = rc(<PdfPreviewPane statementId={null} />);
E(S.getByText("PDF Preview")).toBeInTheDocument();
r0.unmount();
dl.mockResolvedValueOnce({ blob: new Blob(["%PDF-1.4"]), filename: "f.pdf" });
URL.createObjectURL = vi.fn(() => "blob:p1");
URL.revokeObjectURL = vi.fn();
const r1 = rc(<PdfPreviewPane statementId="s1" hasDocument />);
const iframe = await S.findByTitle("Statement PDF preview");
E(dl).toHaveBeenCalledWith("get_statement_document_statements__statement_id__document_get", { path: { statement_id: "s1" } });
E(iframe).toHaveAttribute("src", "blob:p1");
E(iframe).not.toHaveAttribute("sandbox");
E(iframe).toHaveAttribute("referrerPolicy", "no-referrer");
r1.unmount();
E(URL.revokeObjectURL).toHaveBeenCalledWith("blob:p1");
dl.mockClear();
const r2 = rc(<PdfPreviewPane statementId="s1" hasDocument={false} />);
E(dl).not.toHaveBeenCalled();
E(S.getByText("PDF preview not available")).toBeInTheDocument();
r2.unmount();
dl.mockRejectedValueOnce(new Error("502"));
rc(<>
<PdfPreviewPane statementId="s1" hasDocument />
<TransactionTable currency="SGD" transactions={[{ id: "1", statement_id: "s1", txn_date: "2024-01-01", description: "Test Txn", amount: "100.0", direction: "OUT", reference: null, currency: "SGD", balance_after: null, status: "pending", confidence: "high", created_at: "2024-01-01T00:00:00Z", updated_at: "2024-01-01T00:00:00Z" }]} />
<ConflictResolutionDialog isOpen onClose={() => {}} duplicateCandidates={[]} transferPairCandidates={[]} />
<BottomTabBar />
</>);
E(await S.findByText("PDF preview could not be loaded")).toBeInTheDocument();
E(S.getAllByText("Test Txn").length > 0 && S.getAllByText("high").length > 0).toBe(true);
for (const t of ["Review possible duplicates", "No conflicts detected for this statement.", "Home"]) E(S.getByText(t)).toBeInTheDocument();
E(S.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
});
// AC-extraction.fe-stage1-review.12
