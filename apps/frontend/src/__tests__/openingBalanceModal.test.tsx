import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OpeningBalanceModal from "@/components/accounts/OpeningBalanceModal";
import { apiFetch } from "@/lib/api";
import type { Account } from "@/lib/types";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));

const mockedApi = vi.mocked(apiFetch);

const accounts: Account[] = [
    { id: "a1", name: "Cash", type: "ASSET", currency: "SGD", is_active: true },
    { id: "a2", name: "Credit Card", type: "LIABILITY", currency: "SGD", is_active: true },
    { id: "a3", name: "Salary", type: "INCOME", currency: "SGD", is_active: true },
    { id: "a4", name: "Closed", type: "ASSET", currency: "SGD", is_active: false },
];

describe("OpeningBalanceModal (#949 / AC2.15.8)", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("AC-ledger.first-use.1 explicitly applies the prior-period date without posting", async () => {
        mockedApi.mockResolvedValueOnce({ id: "opening-entry" });
        render(<OpeningBalanceModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} accounts={accounts} />);
        const date = screen.getByLabelText("As-of date *");
        expect(date).toHaveValue("");
        fireEvent.change(screen.getByLabelText("First report period starts"), { target: { value: "2026-03-01" } });
        expect(date).toHaveValue("");
        fireEvent.click(screen.getByRole("button", { name: "Use 2026-02-28" }));
        expect(date).toHaveValue("2026-02-28");
        expect(mockedApi).not.toHaveBeenCalled();
        fireEvent.change(date, { target: { value: "2026-02-27" } });
        fireEvent.change(screen.getByLabelText("First report period starts"), { target: { value: "2026-04-01" } });
        expect(date).toHaveValue("2026-02-27");
        fireEvent.change(screen.getByLabelText("Opening balance for Cash"), { target: { value: "100.00" } });
        fireEvent.click(screen.getByRole("button", { name: "Record opening balances" }));
        await waitFor(() => expect(mockedApi).toHaveBeenCalledTimes(1));
        expect(JSON.parse(mockedApi.mock.calls[0][1]?.body as string).entry_date).toBe("2026-02-27");
    });

    it.each([
        ["2024-03-01", "2024-02-29"],
        ["2026-01-01", "2025-12-31"],
    ])("AC-ledger.first-use.1 suggests the previous calendar day for %s", (period, expected) => {
        render(<OpeningBalanceModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} accounts={accounts} />);
        fireEvent.change(screen.getByLabelText("First report period starts"), { target: { value: period } });
        fireEvent.click(screen.getByRole("button", { name: `Use ${expected}` }));
        expect(screen.getByLabelText("As-of date *")).toHaveValue(expected);
    });

    it("AC-ledger.first-use.1 rejects an opening date inside the selected period", async () => {
        render(<OpeningBalanceModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} accounts={accounts} />);
        fireEvent.change(screen.getByLabelText("First report period starts"), { target: { value: "2026-03-01" } });
        fireEvent.change(screen.getByLabelText("As-of date *"), { target: { value: "2026-03-01" } });
        fireEvent.change(screen.getByLabelText("Opening balance for Cash"), { target: { value: "100.00" } });
        fireEvent.click(screen.getByRole("button", { name: "Record opening balances" }));
        expect(await screen.findByText("Opening balances must be dated before the first report period starts.")).toBeInTheDocument();
        expect(mockedApi).not.toHaveBeenCalled();
    });

    it("AC-ledger.first-use.1 starts a reopened dialog without a stale date or amount", () => {
        const props = { onClose: vi.fn(), onSuccess: vi.fn(), accounts };
        const { rerender } = render(<OpeningBalanceModal {...props} isOpen />);
        fireEvent.change(screen.getByLabelText("First report period starts"), { target: { value: "2026-03-01" } });
        fireEvent.click(screen.getByRole("button", { name: "Use 2026-02-28" }));
        fireEvent.change(screen.getByLabelText("Opening balance for Cash"), { target: { value: "100" } });
        rerender(<OpeningBalanceModal {...props} isOpen={false} />);
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
        rerender(<OpeningBalanceModal {...props} isOpen />);
        expect(screen.getByLabelText("First report period starts")).toHaveValue("");
        expect(screen.getByLabelText("As-of date *")).toHaveValue("");
        expect(screen.getByLabelText("Opening balance for Cash")).toHaveValue("");
    });

    it("AC2.15.8 lists only eligible accounts and hides income/expense and inactive ones", () => {
        render(<OpeningBalanceModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} accounts={accounts} />);

        expect(screen.getByLabelText("Opening balance for Cash")).toBeInTheDocument();
        expect(screen.getByLabelText("Opening balance for Credit Card")).toBeInTheDocument();
        expect(screen.queryByLabelText("Opening balance for Salary")).not.toBeInTheDocument();
        expect(screen.queryByLabelText("Opening balance for Closed")).not.toBeInTheDocument();
    });

    it("AC2.15.8 posts a balances map without requiring hand-written journal lines", async () => {
        mockedApi.mockResolvedValueOnce({ id: "entry-1" });
        const onSuccess = vi.fn();
        const onClose = vi.fn();
        render(<OpeningBalanceModal isOpen onClose={onClose} onSuccess={onSuccess} accounts={accounts} />);

        fireEvent.change(screen.getByLabelText("As-of date *"), { target: { value: "2026-01-01" } });
        fireEvent.change(screen.getByLabelText("Opening balance for Cash"), { target: { value: "1500.50" } });
        fireEvent.click(screen.getByRole("button", { name: "Record opening balances" }));

        await waitFor(() => expect(mockedApi).toHaveBeenCalledTimes(1));
        const [path, init] = mockedApi.mock.calls[0];
        expect(path).toBe("/api/accounts/opening-balances");
        expect(init?.method).toBe("POST");
        expect(JSON.parse(init?.body as string)).toEqual({
            entry_date: "2026-01-01",
            balances: { a1: "1500.50" },
            memo: "Opening balances",
        });
        await waitFor(() => expect(onSuccess).toHaveBeenCalled());
        expect(onClose).toHaveBeenCalled();
    });

    it("AC2.15.8 sends a custom memo and as-of date entered by the user", async () => {
        mockedApi.mockResolvedValueOnce({ id: "entry-2" });
        render(<OpeningBalanceModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} accounts={accounts} />);

        fireEvent.change(screen.getByLabelText("As-of date *"), { target: { value: "2025-01-01" } });
        fireEvent.change(screen.getByLabelText("Memo"), { target: { value: "Year-start positions" } });
        fireEvent.change(screen.getByLabelText("Opening balance for Cash"), { target: { value: "42.00" } });
        fireEvent.click(screen.getByRole("button", { name: "Record opening balances" }));

        await waitFor(() => expect(mockedApi).toHaveBeenCalledTimes(1));
        expect(JSON.parse(mockedApi.mock.calls[0][1]?.body as string)).toEqual({
            entry_date: "2025-01-01",
            balances: { a1: "42.00" },
            memo: "Year-start positions",
        });
    });

    it("AC2.15.8 prompts to create an eligible account when none exist", () => {
        render(<OpeningBalanceModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} accounts={[]} />);

        expect(
            screen.getByText("Create an asset, liability, or equity account first, then set its opening balance."),
        ).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Record opening balances" })).toBeDisabled();
    });

    it("AC2.15.8 blocks submission until at least one positive balance is entered", async () => {
        render(<OpeningBalanceModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} accounts={accounts} />);

        fireEvent.change(screen.getByLabelText("As-of date *"), { target: { value: "2026-01-01" } });

        fireEvent.click(screen.getByRole("button", { name: "Record opening balances" }));

        expect(await screen.findByText("Enter a starting balance for at least one account.")).toBeInTheDocument();
        expect(mockedApi).not.toHaveBeenCalled();
    });

    it("AC2.15.8 blocks submission when the as-of date is cleared", async () => {
        render(<OpeningBalanceModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} accounts={accounts} />);

        fireEvent.change(screen.getByLabelText("As-of date *"), { target: { value: "" } });
        fireEvent.change(screen.getByLabelText("Opening balance for Cash"), { target: { value: "100" } });
        fireEvent.click(screen.getByRole("button", { name: "Record opening balances" }));

        expect(
            await screen.findByText("Enter the as-of date for these opening balances."),
        ).toBeInTheDocument();
        expect(mockedApi).not.toHaveBeenCalled();
    });

    it("AC2.15.8 rejects non-positive or over-precise amounts before calling the API", async () => {
        render(<OpeningBalanceModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} accounts={accounts} />);

        fireEvent.change(screen.getByLabelText("As-of date *"), { target: { value: "2026-01-01" } });

        fireEvent.change(screen.getByLabelText("Opening balance for Cash"), { target: { value: "1.234" } });
        fireEvent.click(screen.getByRole("button", { name: "Record opening balances" }));

        expect(
            await screen.findByText("Balances must be positive amounts with at most two decimal places."),
        ).toBeInTheDocument();
        expect(mockedApi).not.toHaveBeenCalled();
    });

    it("AC2.15.8 surfaces a backend error instead of closing", async () => {
        mockedApi.mockRejectedValueOnce(new Error("Account has activity before this date"));
        const onClose = vi.fn();
        render(<OpeningBalanceModal isOpen onClose={onClose} onSuccess={vi.fn()} accounts={accounts} />);

        fireEvent.change(screen.getByLabelText("As-of date *"), { target: { value: "2026-01-01" } });

        fireEvent.change(screen.getByLabelText("Opening balance for Cash"), { target: { value: "100" } });
        fireEvent.click(screen.getByRole("button", { name: "Record opening balances" }));

        expect(await screen.findByText("Account has activity before this date")).toBeInTheDocument();
        expect(onClose).not.toHaveBeenCalled();
    });
});
