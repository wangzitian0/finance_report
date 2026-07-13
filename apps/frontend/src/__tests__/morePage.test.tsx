import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import MorePage from "@/app/(main)/more/page";
import { apiFetch } from "@/lib/api";
import { clearUser } from "@/lib/auth";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
    useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("@/lib/auth", () => ({ clearUser: vi.fn() }));

const mockedApiFetch = vi.mocked(apiFetch);

describe("More overflow (EPIC-022 AC22.21.5)", () => {
    beforeEach(() => {
        pushMock.mockReset();
        mockedApiFetch.mockReset();
    });

    it("lists Settings, Advanced/Accounts, and Logout, and logs out", async () => {
        mockedApiFetch.mockResolvedValue({ items: [], total: 0, warnings: [] });
        render(<MorePage />);

        expect(screen.getByRole("link", { name: /Settings/i })).toHaveAttribute("href", "/settings");
        expect(screen.getByRole("link", { name: /Accounts/i })).toHaveAttribute("href", "/accounts");

        fireEvent.click(screen.getByRole("button", { name: /Logout/i }));
        expect(clearUser).toHaveBeenCalledTimes(1);
        expect(pushMock).toHaveBeenCalledWith("/login");
    });

    it("hides Portfolio when the user holds no securities", async () => {
        mockedApiFetch.mockResolvedValue({ items: [], total: 0, warnings: [] });
        render(<MorePage />);
        await waitFor(() => expect(mockedApiFetch).toHaveBeenCalled());
        expect(screen.queryByRole("link", { name: /Portfolio/i })).toBeNull();
    });

    it("shows Portfolio once the user holds securities", async () => {
        mockedApiFetch.mockResolvedValue({ items: [{ ticker: "AAPL" }], total: 1, warnings: [] });
        render(<MorePage />);
        await waitFor(() =>
            expect(screen.getByRole("link", { name: /Portfolio/i })).toHaveAttribute("href", "/portfolio"),
        );
    });
});
