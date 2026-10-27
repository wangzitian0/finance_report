import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import MorePage from "@/app/(main)/more/page";
import { apiOperation } from "@/lib/api-client";
import { clearUser } from "@/lib/auth";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
    useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }));
vi.mock("@/lib/auth", () => ({ clearUser: vi.fn() }));

const mockedApiOperation = vi.mocked(apiOperation);

describe("More overflow (EPIC-022 AC22.21.5)", () => {
    beforeEach(() => {
        pushMock.mockReset();
        mockedApiOperation.mockReset();
        vi.mocked(clearUser).mockReset();
    });

    it("lists Portfolio, Reports, Settings, Advanced/Accounts, and Logout without gating on brokerage holdings", async () => {
        render(<MorePage />);

        expect(screen.getByRole("link", { name: /Portfolio/i })).toHaveAttribute("href", "/portfolio");
        expect(screen.getByRole("link", { name: /Reports/i })).toHaveAttribute("href", "/reports");
        expect(screen.getByRole("link", { name: /Settings/i })).toHaveAttribute("href", "/settings");
        expect(screen.getByRole("link", { name: /Accounts/i })).toHaveAttribute("href", "/settings?tab=accounts");
        expect(mockedApiOperation).not.toHaveBeenCalledWith("get_holdings_portfolio_holdings_get");

        fireEvent.click(screen.getByRole("button", { name: /Logout/i }));
        await waitFor(() => expect(clearUser).toHaveBeenCalledTimes(1));
        expect(pushMock).toHaveBeenCalledWith("/login");
    });

    // AC-identity.fe-auth.15
    it("keeps mobile identity when logout fails", async () => {
        mockedApiOperation.mockImplementation(async (operationId) => {
            if (operationId === "logout_auth_logout_post") throw new Error("Offline");
            return { items: [] } as any;
        });
        render(<MorePage />);
        fireEvent.click(screen.getByRole("button", { name: "Logout" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("Could not log out. Please try again.");
        expect(clearUser).not.toHaveBeenCalled();
        expect(pushMock).not.toHaveBeenCalled();
        expect(screen.getByRole("button", { name: "Logout" })).toBeEnabled();
    });
});
