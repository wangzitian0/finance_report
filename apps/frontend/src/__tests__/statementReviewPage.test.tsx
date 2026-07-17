import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";

import StatementReviewPage from "@/app/(main)/statements/[id]/review/page";
import { ToastProvider } from "@/components/ui/Toast";
import { ApiError, apiFetch } from "@/lib/api";
import { track, ANALYTICS_EVENTS } from "@/lib/analytics";

import { createInvalidationProbe } from "./fixtures/invalidationProbe";
import { renderReviewComponent } from "./helpers/renderReviewComponent";

const navigationState = vi.hoisted(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    searchParams: new URLSearchParams(),
}));
const pushMock = navigationState.push;
const replaceMock = navigationState.replace;

vi.mock("@/lib/api", async (importOriginal) => ({
    ...(await importOriginal<typeof import("@/lib/api")>()),
    apiFetch: vi.fn(),
    // PdfPreviewPane fetches the document blob on mount (#963 / AC16.33.5).
    apiDownload: vi.fn(() => Promise.resolve({ blob: new Blob(["%PDF"]), filename: "f.pdf" })),
}));
vi.mock("next/navigation", () => ({
    useRouter: vi.fn(() => ({ replace: replaceMock, push: pushMock })),
    useParams: vi.fn(() => ({ id: "s1" })),
    useSearchParams: vi.fn(() => navigationState.searchParams),
}));
vi.mock("@/lib/analytics", async (importOriginal) => ({
    ...(await importOriginal<typeof import("@/lib/analytics")>()),
    track: vi.fn(),
}));

const mockedApi = vi.mocked(apiFetch);

const baseStatement = {
    id: "s1",
    original_filename: "statement.pdf",
    institution: "DBS",
    currency: "SGD",
    period_start: "2024-01-01",
    period_end: "2024-01-31",
    opening_balance: 100,
    closing_balance: 120,
    status: "pending",
    stage1_status: null,
    balance_validation_result: {
        opening_balance: "100.00",
        closing_balance: "120.00",
        calculated_closing: "120.00",
        opening_delta: "0.00",
        closing_delta: "0.00",
        opening_match: true,
        closing_match: true,
        validated_at: "2024-01-31T00:00:00Z",
    },
    pdf_url: null,
    transactions: [
        {
            id: "txn-1",
            txn_date: "2024-01-03",
            description: "Salary",
            reference: "REF-1",
            amount: 20,
            direction: "IN",
            currency: "SGD",
            balance_after: 120,
            confidence: "high",
            status: "draft",
        },
    ],
};

const emptyConflicts = { duplicates: [], transfer_pairs: [] };

describe("AC16.1.2 AC16.1.3 Statement review page", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        navigationState.searchParams = new URLSearchParams();
    });

    // AC-extraction.fe-stage1-review.7
    it("AC16.18.4 shows loading feedback while review data is pending", () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                return new Promise(() => undefined) as Promise<never>;
            }

            return Promise.resolve({ items: [{ id: "s1" }] });
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        expect(screen.getByText("Loading review data...")).toBeInTheDocument();
    });

    it("AC16.18.4 shows error fallback and retries the statement review fetch", async () => {
        let reviewAttempts = 0;

        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                reviewAttempts += 1;
                if (reviewAttempts === 1) {
                    return Promise.reject(new Error("network fail"));
                }

                return Promise.resolve(baseStatement);
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }

            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve(emptyConflicts);
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        expect(await screen.findByText("Failed to load statement")).toBeInTheDocument();
        expect(screen.getByText("network fail")).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: "Retry" }));

        expect(await screen.findByText("statement.pdf")).toBeInTheDocument();
        expect(reviewAttempts).toBe(2);
    });

    // AC-extraction.fe-stage1-review.8
    it("AC16.18.5 disables approve when balance validation fails", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve({
                    ...baseStatement,
                    balance_validation_result: {
                        ...baseStatement.balance_validation_result,
                        closing_match: false,
                    },
                });
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }

            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve(emptyConflicts);
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        const approveButton = await screen.findByRole("button", { name: "Approve" });
        expect(approveButton).toBeDisabled();
    });

    it("AC-extraction.reviewed-envelope.6 confirms missing source envelope facts before approval", async () => {
        let confirmed = false;
        mockedApi.mockImplementation((path: string, options?: RequestInit) => {
            if (path === "/api/statements/s1/review") {
                if (confirmed) {
                    return Promise.resolve({
                        ...baseStatement,
                        account_id: "a1",
                        source_result_digest: "a".repeat(64),
                        source_missing_facts: ["statement_currency", "period", "balances"],
                        reviewed_envelope: {
                            id: "review-1",
                            source_result_digest: "a".repeat(64),
                            account_id: "a1",
                            currency: "SGD",
                            period_start: "2024-01-01",
                            period_end: "2024-01-31",
                            opening_balance: "100.00",
                            closing_balance: "120.00",
                            rationale: "The CSV has no statement header.",
                            review_trace_record_id: "trace-1",
                            created_at: "2024-02-01T00:00:00Z",
                        },
                    });
                }
                return Promise.resolve({
                    ...baseStatement,
                    account_id: null,
                    currency: null,
                    period_start: null,
                    opening_balance: null,
                    closing_balance: null,
                    source_result_digest: "a".repeat(64),
                    source_missing_facts: ["statement_currency", "period", "balances"],
                    source_envelope_reviewable: true,
                    reviewed_envelope: null,
                });
            }
            if (path === "/api/accounts?account_type=ASSET&is_active=true") {
                return Promise.resolve({
                    items: [{ id: "a1", name: "DBS Cash", type: "ASSET", currency: "SGD", is_active: true }],
                    total: 1,
                });
            }
            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }
            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve(emptyConflicts);
            }
            if (path === "/api/statements/s1/review/envelope") {
                expect(options).toMatchObject({ method: "POST" });
                expect(JSON.parse(String(options?.body))).toMatchObject({
                    source_result_digest: "a".repeat(64),
                    account_id: "a1",
                    currency: "SGD",
                    period_start: "2024-01-01",
                    period_end: "2024-01-31",
                    opening_balance: "100",
                    closing_balance: "120",
                });
                confirmed = true;
                return Promise.resolve({ id: "review-1" });
            }
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        const probe = createInvalidationProbe("statements.review.confirm-envelope", ["s1"]);
        const ProbeWrapper = ({ children }: { children: ReactNode }) => (
            <probe.wrapper>
                <ToastProvider>{children}</ToastProvider>
            </probe.wrapper>
        );
        render(<StatementReviewPage /> as never, { wrapper: ProbeWrapper });

        expect(await screen.findByText("Confirm missing source facts")).toBeInTheDocument();
        expect(screen.getByText(/statement currency, statement period, opening and closing balances/i)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();

        fireEvent.change(screen.getByLabelText("Custody account"), { target: { value: "a1" } });
        fireEvent.change(screen.getByLabelText("Statement currency"), { target: { value: "SGD" } });
        fireEvent.change(screen.getByLabelText("Period start"), { target: { value: "2024-01-01" } });
        fireEvent.change(screen.getByLabelText("Period end"), { target: { value: "2024-01-31" } });
        fireEvent.change(screen.getByLabelText("Opening balance"), { target: { value: "100" } });
        fireEvent.change(screen.getByLabelText("Closing balance"), { target: { value: "120" } });
        fireEvent.change(screen.getByLabelText("Why are these facts confirmed?"), {
            target: { value: "The CSV has no statement header." },
        });
        fireEvent.click(screen.getByRole("button", { name: "Confirm source envelope" }));

        await waitFor(() => {
            expect(mockedApi).toHaveBeenCalledWith(
                "/api/statements/s1/review/envelope",
                expect.objectContaining({ method: "POST" }),
            );
        });
        await waitFor(() => probe.expectDeclaredInvalidated());
        await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled());
    });

    it("AC-extraction.reviewed-envelope.6 does not offer a cash envelope for unsupported source facts", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve({
                    ...baseStatement,
                    source_result_digest: "a".repeat(64),
                    source_missing_facts: ["transaction_currency"],
                    source_envelope_reviewable: false,
                    reviewed_envelope: null,
                });
            }
            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }
            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve(emptyConflicts);
            }
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        expect(await screen.findByText("Source review required")).toBeInTheDocument();
        expect(screen.getByText(/transaction currency cannot be confirmed by a cash statement envelope/i)).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Confirm source envelope" })).not.toBeInTheDocument();
        expect(screen.queryByLabelText("Custody account")).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    });

    // AC-extraction.fe-stage1-review.9
    it("AC16.18.6 approves the statement and routes back to statement detail", async () => {
        mockedApi.mockImplementation((path: string, options?: RequestInit) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve(baseStatement);
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }

            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve(emptyConflicts);
            }

            if (path === "/api/statements/s1/review/approve") {
                expect(options).toMatchObject({ method: "POST" });
                return Promise.resolve({ journal_entries_created: 2 });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        fireEvent.click(await screen.findByRole("button", { name: "Approve" }));

        const dialog = await screen.findByRole("dialog", { name: "Approve Statement" });
        fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }));

        await waitFor(() => {
            expect(pushMock).toHaveBeenCalledWith("/statements/s1?approved=1&entriesCreated=2");
        });
    });

    it("AC22.18.3 tracks REVIEW_APPROVED with the statement id on a successful approve", async () => {
        mockedApi.mockImplementation((path: string, options?: RequestInit) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve(baseStatement);
            }
            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }
            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve(emptyConflicts);
            }
            if (path === "/api/statements/s1/review/approve") {
                expect(options).toMatchObject({ method: "POST" });
                return Promise.resolve({ journal_entries_created: 2 });
            }
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
        const dialog = await screen.findByRole("dialog", { name: "Approve Statement" });
        fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }));

        await waitFor(() => {
            expect(vi.mocked(track)).toHaveBeenCalledWith(
                ANALYTICS_EVENTS.REVIEW_APPROVED,
                expect.objectContaining({ statement_id: "s1" }),
            );
        });
    });

    it("AC-extraction.disposition.5 keeps the review open when economic classification is required", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve(baseStatement);
            }
            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }
            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve(emptyConflicts);
            }
            if (path === "/api/statements/s1/review/approve") {
                return Promise.reject(new ApiError("Economic review required: intent_missing", 409));
            }
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
        const dialog = await screen.findByRole("dialog", { name: "Approve Statement" });
        fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }));

        await waitFor(() => {
            expect(screen.getByText("Economic classification needs review before entries can be posted.")).toBeInTheDocument();
        });
        expect(pushMock).not.toHaveBeenCalled();
        expect(track).not.toHaveBeenCalledWith(
            ANALYTICS_EVENTS.REVIEW_APPROVED,
            expect.objectContaining({ statement_id: "s1" }),
        );
    });

    it("AC16.34.3 resolves Stage-1 conflicts and unblocks approval", async () => {
        const duplicate = {
            id: "t1",
            txn_date: "2025-01-15",
            description: "Duplicate deposit",
            amount: "20.00",
            direction: "IN",
        };
        mockedApi.mockImplementation((path: string, options?: RequestInit) => {
            if (path === "/api/statements/s1/review") return Promise.resolve(baseStatement);
            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }
            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve({ duplicates: [duplicate, duplicate], transfer_pairs: [] });
            }
            if (path === "/api/review/conflicts/s1/resolve") {
                expect(options).toMatchObject({ method: "POST" });
                expect(JSON.parse(options?.body as string)).toEqual({ action: "confirm_distinct" });
                return Promise.resolve({ resolved: true, resolved_at: "2026-06-14T00:00:00Z" });
            }
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        // The conflict dialog auto-opens; resolve the duplicate candidates.
        const resolveButtons = await screen.findAllByRole("button", { name: "Resolve" });
        fireEvent.click(resolveButtons[0]);

        await waitFor(() => {
            expect(mockedApi).toHaveBeenCalledWith(
                "/api/review/conflicts/s1/resolve",
                expect.objectContaining({ method: "POST" }),
            );
        });
    });

    it("AC-testing.fe-async.2 resolve-conflicts flow invalidates the matrix-declared query keys against a real QueryClient", async () => {
        // #1827 G-async-seam: only apiFetch is mocked; react-query runs for
        // real. The declared ["statement-conflicts"] prefix extends to the
        // runtime ["statement-conflicts", statementId] key via fuzzy matching.
        const duplicate = {
            id: "t1",
            txn_date: "2025-01-15",
            description: "Duplicate deposit",
            amount: "20.00",
            direction: "IN",
        };
        mockedApi.mockImplementation((path: string, options?: RequestInit) => {
            if (path === "/api/statements/s1/review") return Promise.resolve(baseStatement);
            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }
            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve({ duplicates: [duplicate, duplicate], transfer_pairs: [] });
            }
            if (path === "/api/review/conflicts/s1/resolve" && options?.method === "POST") {
                return Promise.resolve({ resolved: true, resolved_at: "2026-06-14T00:00:00Z" });
            }
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        const probe = createInvalidationProbe("statements.review.resolve-conflicts", ["s1"]);
        const ProbeWrapper = ({ children }: { children: ReactNode }) => (
            <probe.wrapper>
                <ToastProvider>{children}</ToastProvider>
            </probe.wrapper>
        );
        render(<StatementReviewPage /> as never, { wrapper: ProbeWrapper });

        const resolveButtons = await screen.findAllByRole("button", { name: "Resolve" });
        probe.expectNothingInvalidated();
        fireEvent.click(resolveButtons[0]);

        await waitFor(() => {
            expect(mockedApi).toHaveBeenCalledWith(
                "/api/review/conflicts/s1/resolve",
                expect.objectContaining({ method: "POST" }),
            );
        });
        await waitFor(() => probe.expectDeclaredInvalidated());
    });

    it("AC16.34.3 keeps approval unblocked when the server marks conflicts resolved", async () => {
        const duplicate = {
            id: "t1",
            txn_date: "2025-01-15",
            description: "Duplicate deposit",
            amount: "20.00",
            direction: "IN",
        };
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") return Promise.resolve(baseStatement);
            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }
            if (path === "/api/review/conflicts/s1") {
                // Persisted resolution marker from a prior session/tab.
                return Promise.resolve({ duplicates: [duplicate, duplicate], transfer_pairs: [], resolved: true });
            }
            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        // Approve stays enabled and the conflict dialog does not force itself open.
        const approveButton = await screen.findByRole("button", { name: "Approve" });
        expect(approveButton).not.toBeDisabled();
        expect(screen.queryByText("Resolve Conflicts")).not.toBeInTheDocument();
    });

    it("AC16.18.6 rejects the statement with notes and routes back to statements", async () => {
        mockedApi.mockImplementation((path: string, options?: RequestInit) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve(baseStatement);
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }

            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve(emptyConflicts);
            }

            if (path === "/api/statements/s1/review/reject") {
                expect(options).toMatchObject({
                    method: "POST",
                    body: JSON.stringify({ notes: "Needs re-parse" }),
                });
                return Promise.resolve({ success: true });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        fireEvent.click(await screen.findByRole("button", { name: "Reject" }));

        const dialog = await screen.findByRole("dialog", { name: "Reject Statement" });
        fireEvent.change(within(dialog).getByRole("textbox"), {
            target: { value: "Needs re-parse" },
        });
        fireEvent.click(within(dialog).getByRole("button", { name: "Reject" }));

        await waitFor(() => {
            expect(pushMock).toHaveBeenCalledWith("/statements");
        });
    });

    it("AC16.18.6 lets reviewers move to adjacent pending statements", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve(baseStatement);
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({
                    items: [{ id: "s0" }, { id: "s1" }, { id: "s2" }],
                    total: 3,
                });
            }

            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve(emptyConflicts);
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        fireEvent.click(await screen.findByRole("button", { name: "← Prev" }));
        fireEvent.click(screen.getByRole("button", { name: "Next →" }));

        expect(pushMock).toHaveBeenNthCalledWith(1, "/statements/s0/review");
        expect(pushMock).toHaveBeenNthCalledWith(2, "/statements/s2/review");
    });

    it("AC22.11.3 returns attention-origin statement review actions to the attention queue", async () => {
        navigationState.searchParams = new URLSearchParams("from=attention");

        mockedApi.mockImplementation((path: string, options?: RequestInit) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve(baseStatement);
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s0" }, { id: "s1" }, { id: "s2" }], total: 3 });
            }

            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve(emptyConflicts);
            }

            if (path === "/api/statements/s1/review/approve") {
                expect(options).toMatchObject({ method: "POST" });
                return Promise.resolve({ journal_entries_created: 1 });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        const backLink = await screen.findByRole("link", { name: /Back to Attention queue/i });
        expect(backLink).toHaveAttribute("href", "/attention");

        fireEvent.click(screen.getByRole("button", { name: "← Prev" }));
        fireEvent.click(screen.getByRole("button", { name: "Next →" }));

        expect(pushMock).toHaveBeenNthCalledWith(1, "/statements/s0/review?from=attention");
        expect(pushMock).toHaveBeenNthCalledWith(2, "/statements/s2/review?from=attention");

        fireEvent.click(screen.getByRole("button", { name: "Approve" }));
        const dialog = await screen.findByRole("dialog", { name: "Approve Statement" });
        fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }));

        await waitFor(() => {
            expect(pushMock).toHaveBeenLastCalledWith("/attention");
        });
    });

    // AC-reconciliation.fe-stage2-review.18 / AC-reconciliation.fe-stage2-review.23
    it("AC16.23.3 AC16.31.1 opens the conflict dialog when duplicate or transfer-pair candidates exist", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve(baseStatement);
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }

            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve({
                    duplicates: [
                        {
                            description: "Duplicate salary",
                            txn_date: "2024-01-04",
                            amount: "20.00",
                        },
                    ],
                    transfer_pairs: [
                        {
                            description: "Transfer to savings",
                            txn_date: "2024-01-05",
                            amount: "20.00",
                        },
                    ],
                });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        const dialog = await screen.findByRole("dialog", { name: "Resolve Conflicts" });
        expect(within(dialog).getByText("Duplicate Candidates")).toBeInTheDocument();
        expect(within(dialog).getByText("Transfer Pair Candidates")).toBeInTheDocument();
        expect(mockedApi).toHaveBeenCalledWith("/api/review/conflicts/s1");
    });

    // AC-extraction.fe-stage1-review.13
    it("AC16.31.2 disables approval when opening balance validation fails", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve({
                    ...baseStatement,
                    balance_validation_result: {
                        ...baseStatement.balance_validation_result,
                        opening_match: false,
                        closing_match: true,
                    },
                });
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }

            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve(emptyConflicts);
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        const approveButton = await screen.findByRole("button", { name: "Approve" });
        expect(approveButton).toBeDisabled();
    });

    it("AC16.32.1 disables approval while conflict candidates are unresolved", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve(baseStatement);
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }

            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve({
                    duplicates: [
                        {
                            id: "txn-dup",
                            description: "Duplicate salary",
                            txn_date: "2024-01-04",
                            amount: "20.00",
                            direction: "IN",
                        },
                    ],
                    transfer_pairs: [],
                });
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        const approveButton = await screen.findByRole("button", { name: "Approve" });
        expect(approveButton).toBeDisabled();
        expect(approveButton).toHaveAttribute(
            "title",
            "Approve is paused — we found possible duplicate or transfer-pair transactions. Review them before approving.",
        );
        // AC22.5.2: the block is explained in plain language with an in-place escape.
        expect(screen.getByText(/Approve is paused/i)).toBeInTheDocument();
        const autoOpenedDialog = await screen.findByRole("dialog", { name: "Resolve Conflicts" });
        fireEvent.click(within(autoOpenedDialog).getByRole("button", { name: "Close" }));
        await waitFor(() => {
            expect(screen.queryByRole("dialog", { name: "Resolve Conflicts" })).not.toBeInTheDocument();
        });

        fireEvent.click(screen.getByRole("button", { name: /Resolve conflicts/i }));

        expect(await screen.findByRole("dialog", { name: "Resolve Conflicts" })).toBeInTheDocument();
    });

    // AC-extraction.fe-stage1-review.14
    it("AC16.32.2 shows opening and closing balance validation states separately", async () => {
        mockedApi.mockImplementation((path: string) => {
            if (path === "/api/statements/s1/review") {
                return Promise.resolve({
                    ...baseStatement,
                    balance_validation_result: {
                        ...baseStatement.balance_validation_result,
                        opening_match: false,
                        closing_match: true,
                        opening_delta: "5.00",
                        closing_delta: "0.00",
                    },
                });
            }

            if (path === "/api/statements/pending-review") {
                return Promise.resolve({ items: [{ id: "s1" }], total: 1 });
            }

            if (path === "/api/review/conflicts/s1") {
                return Promise.resolve(emptyConflicts);
            }

            return Promise.reject(new Error(`Unexpected path ${path}`));
        });

        renderReviewComponent(<StatementReviewPage /> as never);

        expect(await screen.findByText("Opening Mismatch")).toBeInTheDocument();
        expect(screen.getByText("Closing Valid")).toBeInTheDocument();
        expect(screen.getByText("Opening Δ: 5.00")).toBeInTheDocument();
        expect(screen.getByText("Closing Δ: 0.00")).toBeInTheDocument();
    });
});
