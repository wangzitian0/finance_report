import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import * as currency from "@/lib/currency";
import { TransactionTable } from "@/components/review/TransactionTable";
import type { BankStatementTransaction } from "@/lib/types";

describe("TransactionTable", () => {
    const onEdit = vi.fn();
    const onSave = vi.fn();
    const onDiscard = vi.fn();
    const originalMatchMedia = window.matchMedia;

    beforeEach(() => {
        vi.clearAllMocks();
    });

    afterEach(() => {
        Object.defineProperty(window, "matchMedia", {
            configurable: true,
            writable: true,
            value: originalMatchMedia,
        });
    });

    function mockMobileViewport() {
        Object.defineProperty(window, "matchMedia", {
            configurable: true,
            writable: true,
            value: vi.fn().mockImplementation((query: string) => ({
                matches: true,
                media: query,
                addEventListener: vi.fn(),
                removeEventListener: vi.fn(),
            })),
        });
    }

    const sample: BankStatementTransaction[] = [
        {
            id: "t1",
            statement_id: "s1",
            txn_date: "2024-01-10",
            description: "Coffee",
            amount: "3.5",
            direction: "OUT",
            confidence: "high",
            created_at: "",
            updated_at: "",
            status: "pending",
        },
    ];

    it("AC16.26.1 renders editable mobile transaction cards with approve-edits and discard actions", async () => {
        mockMobileViewport();
        type PendingEdit = Partial<{ description: string; amount: string; direction: string; txn_date: string }>;
        const pending: Map<string, PendingEdit> = new Map();
        pending.set("t1", { description: "Coffee Shop" });

        render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={pending}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        expect(await screen.findByTestId("stage1-mobile-transaction-card-t1")).toBeInTheDocument();

        const description = screen.getByLabelText("Description for t1");
        fireEvent.change(description, { target: { value: "Coffee mobile edit" } });
        expect(onEdit).toHaveBeenCalledWith("t1", "description", "Coffee mobile edit");

        fireEvent.change(screen.getByLabelText("Date for t1"), { target: { value: "2024-01-11" } });
        expect(onEdit).toHaveBeenCalledWith("t1", "txn_date", "2024-01-11");

        fireEvent.change(screen.getByLabelText("Direction for t1"), { target: { value: "IN" } });
        expect(onEdit).toHaveBeenCalledWith("t1", "direction", "IN");

        fireEvent.change(screen.getByLabelText("Amount for t1"), { target: { value: "4.25" } });
        expect(onEdit).toHaveBeenCalledWith("t1", "amount", "4.25");

        fireEvent.click(screen.getByRole("button", { name: /Approve Edits/ }));
        expect(onSave).toHaveBeenCalled();
        fireEvent.click(screen.getByRole("button", { name: /Discard/ }));
        expect(onDiscard).toHaveBeenCalled();
    });

    it("keeps desktop table and mobile first-paint markup when matchMedia is unavailable", () => {
        Object.defineProperty(window, "matchMedia", {
            configurable: true,
            writable: true,
            value: undefined,
        });

        render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={new Map()}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        expect(screen.getByTestId("stage1-mobile-transaction-card-t1")).toBeInTheDocument();
        expect(screen.getAllByText("Coffee").length).toBeGreaterThan(0);
    });

    it("AC16.27.1 keeps mobile transaction cards in the DOM without matchMedia gating", () => {
        Object.defineProperty(window, "matchMedia", {
            configurable: true,
            writable: true,
            value: undefined,
        });

        render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={new Map()}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        expect(screen.getByTestId("stage1-mobile-transaction-card-t1")).toBeInTheDocument();
        expect(screen.getAllByText("Coffee").length).toBeGreaterThan(0);
    });

    it("AC8.13.82/AC16.27.2 exposes a fixed desktop transaction region for responsive UX proofs", () => {
        render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={new Map()}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        const region = screen.getByTestId("stage1-desktop-transaction-region");
        expect(region).toHaveClass("overflow-hidden");
        const table = region.querySelector("table");
        expect(table).toHaveClass("table-fixed", "border-collapse");
        expect(table).toHaveStyle({ width: "calc(100% - 4px)" });
    });

    it("renders rows and shows Approve Edits/Discard when pending edits exist", () => {
        type PendingEdit = Partial<{ description: string; amount: string; direction: string; txn_date: string }>;
        const pending: Map<string, PendingEdit> = new Map();
        pending.set("t1", { description: "Coffee Shop" });

        render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={pending}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        expect(screen.getByText("Transactions")).toBeInTheDocument();
        expect(screen.getAllByText("Coffee Shop").length).toBeGreaterThan(0);
        const saveBtn = screen.getByRole("button", { name: /Approve Edits/ });
        fireEvent.click(saveBtn);
        expect(onSave).toHaveBeenCalled();

        const discardBtn = screen.getByRole("button", { name: /Discard/ });
        fireEvent.click(discardBtn);
        expect(onDiscard).toHaveBeenCalled();
    });

    it("allows entering edit mode on click and triggers onEdit when changing fields", () => {
        type PendingEdit = Partial<{ description: string; amount: string; direction: string; txn_date: string }>;
        const pending: Map<string, PendingEdit> = new Map();

        render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={pending}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        // click description cell to begin edit
        const desktopRegion = within(screen.getByTestId("stage1-desktop-transaction-region"));
        const descCell = desktopRegion.getByText("Coffee");
        fireEvent.click(descCell);
        // simulate typing
        const input = desktopRegion.getByDisplayValue("Coffee");
        fireEvent.change(input, { target: { value: "Coffee - Latte" } });
        expect(onEdit).toHaveBeenCalledWith("t1", "description", "Coffee - Latte");
    });

    it("edits amount and direction inline and calls onEdit, shows + for IN", () => {
        type PendingEdit = Partial<{ description: string; amount: string; direction: string; txn_date: string }>;
        const pending: Map<string, PendingEdit> = new Map();

        const sampleIn: BankStatementTransaction[] = [
            {
                id: "t2",
                statement_id: "s1",
                txn_date: "2024-02-01",
                description: "Salary",
                amount: "1000",
                direction: "IN",
                confidence: "high",
                created_at: "",
                updated_at: "",
                status: "pending",
            } as unknown as BankStatementTransaction,
        ];

        render(
            <TransactionTable
                transactions={sampleIn}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={pending}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        // click amount cell to begin edit
        const desktopRegion = within(screen.getByTestId("stage1-desktop-transaction-region"));
        const amountCell = desktopRegion.getByText("+", { exact: false });
        fireEvent.click(amountCell);

        // select direction dropdown and change to OUT
        const select = desktopRegion.getByDisplayValue("IN");
        fireEvent.change(select, { target: { value: "OUT" } });
        expect(onEdit).toHaveBeenCalledWith("t2", "direction", "OUT");

        // change amount input
        const amtInput = desktopRegion.getByDisplayValue("1000");
        fireEvent.change(amtInput, { target: { value: "900" } });
        expect(onEdit).toHaveBeenCalledWith("t2", "amount", "900");
    });

    it("allows editing date cell and triggers onEdit", () => {
        type PendingEdit = Partial<{ description: string; amount: string; direction: string; txn_date: string }>;
        const pending: Map<string, PendingEdit> = new Map();

        render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={pending}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        const desktopRegion = within(screen.getByTestId("stage1-desktop-transaction-region"));
        const dateCell = desktopRegion.getByText("2024-01-10");
        fireEvent.click(dateCell);
        const dateInput = desktopRegion.getByDisplayValue("2024-01-10");
        fireEvent.change(dateInput, { target: { value: "2024-01-11" } });
        expect(onEdit).toHaveBeenCalledWith("t1", "txn_date", "2024-01-11");
    });

    it("shows ring class when amount or direction pending edit exists", () => {
        type PendingEdit = Partial<{ description: string; amount: string; direction: string; txn_date: string }>;
        const pending: Map<string, PendingEdit> = new Map();
        pending.set("t1", { amount: "5.00", direction: "IN" });

        const { container } = render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={pending}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        // when there's a pending edit on amount/direction we render a ring class on the amount span
        const ring = container.querySelector('.ring-1');
        expect(ring).toBeTruthy();
    });

    it("closes inline editors on blur and on Enter key", () => {
        type PendingEdit = Partial<{ description: string; amount: string; direction: string; txn_date: string }>;
        const pending: Map<string, PendingEdit> = new Map();

        const { container } = render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={pending}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        // begin editing amount by clicking the amount cell
        const desktopRegion = within(screen.getByTestId("stage1-desktop-transaction-region"));
        const amountCell = desktopRegion.getByText(/SGD/);
        fireEvent.click(amountCell);

        // now inputs should be present
        const amtInput = desktopRegion.getByDisplayValue("3.5");
        expect(amtInput).toBeTruthy();

        // press Enter to end edit
        fireEvent.keyDown(amtInput, { key: "Enter" });

        // after ending edit, the input should no longer be in the document
        expect(desktopRegion.queryByDisplayValue("3.5")).toBeNull();
    });

    it("renders negative sign for OUT transactions", () => {
        // sample has direction OUT and amount 3.5 -> should show '-' before amount
        render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={new Map()}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        // look specifically for the currency string prefixed with a minus sign
        const negAmount = within(screen.getByTestId("stage1-desktop-transaction-region")).getByText(/-SGD/);
        expect(negAmount).toBeTruthy();
    });

    it("renders confidence badge classes correctly", () => {
        const three: BankStatementTransaction[] = [
            { ...sample[0], id: 'a', confidence: 'high' } as BankStatementTransaction,
            { ...sample[0], id: 'b', confidence: 'medium' } as BankStatementTransaction,
            { ...sample[0], id: 'c', confidence: 'low' } as BankStatementTransaction,
        ];

        render(
            <TransactionTable
                transactions={three}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={new Map()}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        const desktopRegion = within(screen.getByTestId("stage1-desktop-transaction-region"));
        const high = desktopRegion.getByText('high');
        const medium = desktopRegion.getByText('medium');
        const low = desktopRegion.getByText('low');

        expect(high.className).toContain('badge-success');
        expect(medium.className).toContain('badge-warning');
        expect(low.className).toContain('badge-error');
    });

    it("closes combined amount/direction editor on blur", () => {
        type PendingEdit = Partial<{ description: string; amount: string; direction: string; txn_date: string }>;
        const pending: Map<string, PendingEdit> = new Map();

        const { container } = render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={pending}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        // click amount cell to open combined editor
        const desktopRegion = within(screen.getByTestId("stage1-desktop-transaction-region"));
        const amountCell = desktopRegion.getByText(/SGD/);
        fireEvent.click(amountCell);

        // inputs should be present
        const select = desktopRegion.getByDisplayValue("OUT");
        const input = desktopRegion.getByDisplayValue("3.5");
        expect(select).toBeTruthy();
        expect(input).toBeTruthy();

        // blur the wrapper to simulate leaving the editor (relatedTarget null)
        const wrapper = select.closest("div") as HTMLDivElement;
        fireEvent.blur(wrapper, { relatedTarget: null });

        // after blur the inputs should be removed
        expect(desktopRegion.queryByDisplayValue("3.5")).toBeNull();
    });

    it("calls formatCurrencyLocale for numeric and string amounts", () => {
        const spy = vi.spyOn(currency, "formatCurrencyLocale");

        const mixed: BankStatementTransaction[] = [
            sample[0],
            {
                id: "t3",
                statement_id: "s1",
                txn_date: "2024-03-01",
                description: "Gift",
                amount: "50",
                direction: "IN",
                confidence: "high",
                created_at: "",
                updated_at: "",
                status: "pending",
            } as unknown as BankStatementTransaction,
        ];

        render(
            <TransactionTable
                transactions={mixed}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={new Map()}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        // expect formatCurrencyLocale called for both items
        expect(spy).toHaveBeenCalled();
        // find calls containing the two amounts
        const calls = spy.mock.calls.map((c) => c[0]);
        expect(calls.some((v) => v === "3.5" || v === 3.5)).toBe(true);
        expect(calls.some((v) => v === "50" || v === 50)).toBe(true);

        spy.mockRestore();
    });

    it("changing direction via select calls onEdit and hides editor on blur", () => {
        const pending: Map<string, Partial<{ description: string; amount: string; direction: string; txn_date: string }>> = new Map();

        render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={pending}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        // open editor
        const desktopRegion = within(screen.getByTestId("stage1-desktop-transaction-region"));
        const amountCell = desktopRegion.getByText(/SGD/);
        fireEvent.click(amountCell);

        const select = desktopRegion.getByDisplayValue("OUT");
        fireEvent.change(select, { target: { value: "IN" } });
        expect(onEdit).toHaveBeenCalledWith("t1", "direction", "IN");

        // blur wrapper
        const wrapper = select.closest("div") as HTMLDivElement;
        fireEvent.blur(wrapper, { relatedTarget: null });

        // editor should be closed
        expect(desktopRegion.queryByDisplayValue("IN")).toBeNull();
    });

    it("changing amount input calls onEdit and hides editor on blur", () => {
        const pending: Map<string, Partial<{ description: string; amount: string; direction: string; txn_date: string }>> = new Map();

        render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={pending}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        const desktopRegion = within(screen.getByTestId("stage1-desktop-transaction-region"));
        const amountCell = desktopRegion.getByText(/SGD/);
        fireEvent.click(amountCell);

        const amtInput = desktopRegion.getByDisplayValue("3.5");
        fireEvent.change(amtInput, { target: { value: "4.25" } });
        expect(onEdit).toHaveBeenCalledWith("t1", "amount", "4.25");

        // blur to close
        fireEvent.blur(amtInput, { relatedTarget: null });
        expect(desktopRegion.queryByDisplayValue("4.25")).toBeNull();
    });

    it("renders no ring class when pendingEdits empty and ring when present", () => {
        const { container, rerender } = render(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={new Map()}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        expect(container.querySelector('.ring-1')).toBeNull();

        const pending: Map<string, Partial<{ description: string; amount: string; direction: string; txn_date: string }>> = new Map();
        pending.set("t1", { amount: "5.00" });

        rerender(
            <TransactionTable
                transactions={sample}
                currency="SGD"
                onEdit={onEdit}
                pendingEdits={pending}
                onSave={onSave}
                onDiscard={onDiscard}
                actionLoading={false}
            />
        );

        expect(container.querySelector('.ring-1')).toBeTruthy();
    });
});
