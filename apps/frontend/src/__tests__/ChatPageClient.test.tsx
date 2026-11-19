import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ChatPageClient from "@/components/chat/ChatPageClient";
const getMock = vi.fn(), setMock = vi.fn(), S = screen, E = expect;
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), useSearchParams: () => ({ get: getMock }) }));
vi.mock("next/link", () => ({ __esModule: true, default: ({ href, children, className }: { href: string; children: ReactNode; className?: string }) => <a href={href} className={className}>{children}</a> }));
vi.mock("@/components/chat/ChatPanel", () => ({ __esModule: true, default: ({ initialPrompt }: { initialPrompt?: string | null }) => <div data-testid="cp" data-prompt={initialPrompt ?? ""}>Chat Panel</div> }));
function stubLS(init?: Record<string, string>) {
const m = new Map(init ? Object.entries(init) : []);
vi.stubGlobal("localStorage", { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { setMock(k, v); m.set(k, v); }, removeItem: (k: string) => m.delete(k), clear: () => m.clear() });
}
beforeEach(() => { getMock.mockReset(); setMock.mockReset(); getMock.mockReturnValue(null); stubLS(); });
afterEach(() => vi.unstubAllGlobals());
it("AC16.19.5 AC16.19.6 AC16.20.2 ChatPageClient", async () => {
getMock.mockReturnValue("Analyze");
const r1 = render(<ChatPageClient />);
for (const t of ["AI Advisor", /Ask about spending trends/, /This AI financial advisor provides guidance/, /AI Advisor may produce inaccuracies/]) E(S.getByText(t)).toBeInTheDocument();
E(S.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
E(S.getByRole("link", { name: "Reports" })).toHaveAttribute("href", "/reports?tab=balance-sheet");
E(S.getByTestId("cp")).toHaveAttribute("data-prompt", "Analyze");
E(S.getByRole("region", { name: "Disclaimer" })).toBeInTheDocument();
fireEvent.click(S.getByRole("button", { name: "I understand" }));
await waitFor(() => E(S.queryByText("Disclaimer")).toBeNull());
E(setMock).toHaveBeenCalledWith("ai_advisor_disclaimer_v1", "accepted");
r1.unmount();
stubLS({ ai_advisor_disclaimer_v1: "accepted" });
sessionStorage.setItem("ai_chat_pending_prompt", "Pending");
getMock.mockReturnValue("Query");
render(<ChatPageClient />);
E(S.getByTestId("cp")).toHaveAttribute("data-prompt", "Pending");
E(sessionStorage.getItem("ai_chat_pending_prompt")).toBeNull();
await waitFor(() => E(S.queryByText("Disclaimer")).toBeNull());
});
// AC-advisor.fe-chat.2 AC-advisor.fe-chat.3 AC22.5.6
