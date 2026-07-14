import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConsistencyChecksPanel } from "@/components/review/stage2/ConsistencyChecksPanel";
import { PendingMatchesPanel } from "@/components/review/stage2/PendingMatchesPanel";
import { ResolveCheckDialog } from "@/components/review/stage2/ResolveCheckDialog";
import { RunSummaryPanel } from "@/components/review/stage2/RunSummaryPanel";
import { Stage2Filters } from "@/components/review/stage2/Stage2Filters";
import {
    getCheckTypeLabel,
    getSeverityColor,
    type ConsistencyCheck,
    type PendingMatch,
} from "@/components/review/stage2/types";

// useFocusTrap touches DOM focus APIs; keep it a no-op for isolated unit tests.
vi.mock("@/hooks/useFocusTrap", () => ({ useFocusTrap: vi.fn() }));

function makeMatch(overrides: Partial<PendingMatch> = {}): PendingMatch {
    return {
        id: "m1",
        match_score: 88,
        status: "pending_review",
        created_at: "2026-01-01T00:00:00Z",
        description: "Salary transfer",
        amount: "1200.00",
        txn_date: "2026-01-01",
        ...overrides,
    };
}

function makeCheck(overrides: Partial<ConsistencyCheck> = {}): ConsistencyCheck {
    return {
        id: "c1",
        check_type: "duplicate",
        status: "pending",
        related_txn_ids: [],
        details: { message: "Potential duplicate" },
        severity: "high",
        resolved_at: null,
        resolution_note: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        ...overrides,
    };
}

describe("Stage2 extracted parts", () => {
    // AC-reconciliation.fe-ia-reconciliation.9
    it("AC22.17.2 PendingMatchesPanel renders mobile + desktop rows and wires selection/batch callbacks", () => {
        const onToggleMatch = vi.fn();
        const onToggleAll = vi.fn();
        const onBatchReject = vi.fn();
        const onBatchApprove = vi.fn();

        render(
            <PendingMatchesPanel
                matches={[makeMatch()]}
                selectedMatches={new Set<string>(["m1"])}
                actionLoading={false}
                hasUnresolvedChecks={false}
                onToggleMatch={onToggleMatch}
                onToggleAll={onToggleAll}
                onBatchReject={onBatchReject}
                onBatchApprove={onBatchApprove}
            />,
        );

        // Money rendered from a Decimal string via formatAmount (never float).
        expect(screen.getAllByText("1200.00").length).toBeGreaterThan(0);
        expect(screen.getByText("1 total")).toBeInTheDocument();
        expect(screen.getByText("1 selected")).toBeInTheDocument();

        const card = screen.getByTestId("stage2-mobile-match-card-m1");
        fireEvent.click(within(card).getByRole("checkbox", { name: "Select match m1" }));
        expect(onToggleMatch).toHaveBeenCalledWith("m1");

        // Desktop row click toggles selection.
        const region = within(screen.getByTestId("stage2-desktop-match-region"));
        fireEvent.click(region.getByText("Salary transfer"));
        expect(onToggleMatch).toHaveBeenCalledTimes(2);

        // Single match selected -> "Deselect all" toggle.
        fireEvent.click(screen.getByRole("button", { name: "Deselect all" }));
        expect(onToggleAll).toHaveBeenCalledTimes(1);

        fireEvent.click(screen.getByRole("button", { name: "Reject" }));
        expect(onBatchReject).toHaveBeenCalledTimes(1);

        fireEvent.click(screen.getByRole("button", { name: "Approve Selected" }));
        expect(onBatchApprove).toHaveBeenCalledTimes(1);
    });

    it("AC22.17.2 PendingMatchesPanel covers empty state, dashes, score colors, and disabled approve", () => {
        const { rerender } = render(
            <PendingMatchesPanel
                matches={[]}
                selectedMatches={new Set<string>()}
                actionLoading={false}
                hasUnresolvedChecks={false}
                onToggleMatch={vi.fn()}
                onToggleAll={vi.fn()}
                onBatchReject={vi.fn()}
                onBatchApprove={vi.fn()}
            />,
        );
        expect(screen.getByText("No pending matches")).toBeInTheDocument();
        expect(screen.getByText("0 total")).toBeInTheDocument();

        const matches: PendingMatch[] = [
            makeMatch({ id: "high", match_score: 90, amount: "10.00", description: "High score" }),
            makeMatch({ id: "mid", match_score: 70, amount: undefined, txn_date: undefined, description: undefined }),
            makeMatch({ id: "low", match_score: 30, amount: "5.00", description: "Low score" }),
        ];
        const selected = new Set<string>(["high", "mid", "low"]);
        rerender(
            <PendingMatchesPanel
                matches={matches}
                selectedMatches={selected}
                actionLoading={false}
                hasUnresolvedChecks
                onToggleMatch={vi.fn()}
                onToggleAll={vi.fn()}
                onBatchReject={vi.fn()}
                onBatchApprove={vi.fn()}
            />,
        );

        // All selected -> button reads "Deselect all".
        expect(screen.getByRole("button", { name: "Deselect all" })).toBeInTheDocument();
        // Missing amount/date/description render an em dash.
        expect(screen.getAllByText("—").length).toBeGreaterThan(0);
        // Approve disabled because hasUnresolvedChecks is true; carries the guard title.
        const approve = screen.getByRole("button", { name: "Approve Selected" });
        expect(approve).toBeDisabled();
        expect(approve).toHaveAttribute("title", "Resolve consistency checks first");

        // Score color branches: high (success), mid (warning), low (error).
        const highScore = screen.getAllByText("90")[0];
        expect(highScore).toHaveClass("text-[var(--success)]");
        const midScore = screen.getAllByText("70")[0];
        expect(midScore).toHaveClass("text-[var(--warning)]");
        const lowScore = screen.getAllByText("30")[0];
        expect(lowScore).toHaveClass("text-[var(--error)]");
    });

    it("AC22.17.2 PendingMatchesPanel header checkbox reflects full selection and processing state", () => {
        const onBatchApprove = vi.fn();
        render(
            <PendingMatchesPanel
                matches={[makeMatch()]}
                selectedMatches={new Set<string>(["m1"])}
                actionLoading
                hasUnresolvedChecks={false}
                onToggleMatch={vi.fn()}
                onToggleAll={vi.fn()}
                onBatchReject={vi.fn()}
                onBatchApprove={onBatchApprove}
            />,
        );

        // actionLoading -> approve label switches to "Processing..." and is disabled.
        const approve = screen.getByRole("button", { name: "Processing..." });
        expect(approve).toBeDisabled();
        expect(approve).toHaveAttribute("title", "");

        // Desktop header checkbox is checked when every match is selected.
        const region = screen.getByTestId("stage2-desktop-match-region");
        const headerCheckbox = region.querySelector("thead input[type='checkbox']") as HTMLInputElement;
        expect(headerCheckbox).toBeChecked();
    });

    it("ConsistencyChecksPanel renders rows, message fallback, and resolve callback", () => {
        const onResolve = vi.fn();
        const checks: ConsistencyCheck[] = [
            makeCheck(),
            makeCheck({ id: "c2", check_type: "manual_review", severity: "low", details: { reason: "needs eyes" } }),
        ];
        render(<ConsistencyChecksPanel checks={checks} onResolve={onResolve} />);

        expect(screen.getByText("2 total")).toBeInTheDocument();
        expect(screen.getByText("Potential duplicate")).toBeInTheDocument();
        // No `message` key -> JSON.stringify fallback.
        expect(screen.getByText(JSON.stringify({ reason: "needs eyes" }))).toBeInTheDocument();
        // Custom check type falls through to raw type label.
        expect(screen.getByText("manual_review")).toBeInTheDocument();

        fireEvent.click(screen.getAllByRole("button", { name: "Resolve" })[0]);
        expect(onResolve).toHaveBeenCalledWith(checks[0]);
    });

    it("ConsistencyChecksPanel shows the empty state when there are no checks", () => {
        render(<ConsistencyChecksPanel checks={[]} onResolve={vi.fn()} />);
        expect(screen.getByText("No pending checks")).toBeInTheDocument();
        expect(screen.getByText("0 total")).toBeInTheDocument();
    });

    it("Stage2Filters fires every change/toggle callback", () => {
        const onToggleSeverity = vi.fn();
        const onCheckTypeChange = vi.fn();
        const onStatusChange = vi.fn();
        const onMinScoreChange = vi.fn();

        render(
            <Stage2Filters
                checkTypeFilter=""
                statusFilter=""
                severityFilter={["high"]}
                minScore={20}
                onToggleSeverity={onToggleSeverity}
                onCheckTypeChange={onCheckTypeChange}
                onStatusChange={onStatusChange}
                onMinScoreChange={onMinScoreChange}
            />,
        );

        expect(screen.getByText("Min Match Score: 20")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "HIGH" }));
        expect(onToggleSeverity).toHaveBeenCalledWith("high");

        const [checkTypeSelect, statusSelect] = screen.getAllByRole("combobox");
        fireEvent.change(checkTypeSelect, { target: { value: "anomaly" } });
        expect(onCheckTypeChange).toHaveBeenCalledWith("anomaly");
        fireEvent.change(statusSelect, { target: { value: "resolved" } });
        expect(onStatusChange).toHaveBeenCalledWith("resolved");

        fireEvent.change(screen.getByRole("slider"), { target: { value: "45" } });
        expect(onMinScoreChange).toHaveBeenCalledWith(45);
    });

    it("RunSummaryPanel pluralizes counts and wires the approve action", () => {
        const onApproveRun = vi.fn();
        const { rerender } = render(
            <RunSummaryPanel
                runId="run-1"
                unresolvedTransferCount={1}
                unresolvedDuplicateCount={1}
                unresolvedAnomalyCount={1}
                processingPendingCount={0}
                pendingMatchesCount={3}
                actionLoading={false}
                approveRunDisabled={false}
                runApprovalTitle="Approve all pending matches in this run"
                onApproveRun={onApproveRun}
            />,
        );

        // Singular wording branches.
        expect(screen.getByText("1 unresolved transfer")).toBeInTheDocument();
        expect(screen.getByText("1 duplicate")).toBeInTheDocument();
        expect(screen.getByText("1 anomaly")).toBeInTheDocument();
        const approve = screen.getByRole("button", { name: "Approve Run" });
        fireEvent.click(approve);
        expect(onApproveRun).toHaveBeenCalledTimes(1);

        // Plural wording + processing warning + disabled/loading branches.
        rerender(
            <RunSummaryPanel
                runId="run-1"
                unresolvedTransferCount={2}
                unresolvedDuplicateCount={0}
                unresolvedAnomalyCount={2}
                processingPendingCount={4}
                pendingMatchesCount={0}
                actionLoading
                approveRunDisabled
                runApprovalTitle="Resolve consistency checks first"
                onApproveRun={onApproveRun}
            />,
        );
        expect(screen.getByText("2 unresolved transfers")).toBeInTheDocument();
        expect(screen.getByText("0 duplicates")).toBeInTheDocument();
        expect(screen.getByText("2 anomalies")).toBeInTheDocument();
        const disabled = screen.getByRole("button", { name: "Processing..." });
        expect(disabled).toBeDisabled();
        expect(disabled).toHaveAttribute("title", "Resolve consistency checks first");
    });

    it("ResolveCheckDialog resolves, closes via Escape, and ignores Escape while loading", () => {
        const onClose = vi.fn();
        const onResolve = vi.fn();
        const { rerender, unmount } = render(
            <ResolveCheckDialog
                check={makeCheck({ details: {} })}
                actionLoading={false}
                onClose={onClose}
                onResolve={onResolve}
            />,
        );

        const dialog = screen.getByRole("dialog", { name: "Resolve Consistency Check" });
        // Empty details -> JSON.stringify fallback in the summary line.
        expect(within(dialog).getByText(/\{\}/)).toBeInTheDocument();

        fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "note" } });
        fireEvent.click(within(dialog).getByRole("button", { name: "Flag" }));
        expect(onResolve).toHaveBeenCalledWith("flag", "note");

        fireEvent.click(within(dialog).getByRole("button", { name: "Reject" }));
        expect(onResolve).toHaveBeenCalledWith("reject", "note");

        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
        expect(onClose).toHaveBeenCalledTimes(1);

        // Overlay click closes when not loading.
        const overlay = document.querySelector(".fixed.inset-0[aria-hidden='true']") as HTMLElement;
        fireEvent.click(overlay);
        expect(onClose).toHaveBeenCalledTimes(2);

        // Escape closes when not loading.
        fireEvent.keyDown(document, { key: "Escape" });
        expect(onClose).toHaveBeenCalledTimes(3);

        // While loading, overlay + Escape are ignored.
        rerender(
            <ResolveCheckDialog
                check={makeCheck()}
                actionLoading
                onClose={onClose}
                onResolve={onResolve}
            />,
        );
        fireEvent.click(document.querySelector(".fixed.inset-0[aria-hidden='true']") as HTMLElement);
        fireEvent.keyDown(document, { key: "Escape" });
        expect(onClose).toHaveBeenCalledTimes(3);
        expect(screen.getByRole("button", { name: "Processing..." })).toBeDisabled();

        unmount();
    });

    it("severity color + check type label helpers cover all branches", () => {
        expect(getSeverityColor("high")).toBe("text-[var(--error)]");
        expect(getSeverityColor("medium")).toBe("text-[var(--warning)]");
        expect(getSeverityColor("low")).toBe("text-muted");
        expect(getCheckTypeLabel("duplicate")).toBe("Duplicate");
        expect(getCheckTypeLabel("transfer_pair")).toBe("Transfer Pair");
        expect(getCheckTypeLabel("anomaly")).toBe("Anomaly");
        expect(getCheckTypeLabel("manual_review")).toBe("manual_review");
    });
});
