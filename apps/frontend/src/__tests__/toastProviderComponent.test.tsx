import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ToastProvider, useToast } from "@/components/ui/Toast";
function Consumer() {
const { showToast } = useToast();
return <div><button onClick={() => showToast("saved", "success")}>S</button><button onClick={() => showToast("failed", "error")}>E</button><button onClick={() => showToast("warn", "warning")}>W</button></div>;
}
const S = screen, E = expect, clk = (n: string) => fireEvent.click(S.getByRole("button", { name: n })), dis = () => S.getByRole("button", { name: "Dismiss notification" });
it("AC8.13.92 AC16.19.9 AC16.30.4 AC22.12.5 ToastProvider", async () => {
const err = vi.spyOn(console, "error").mockImplementation(() => {});
E(() => render(<Consumer />)).toThrow("useToast must be used within a ToastProvider");
err.mockRestore();
const user = userEvent.setup();
render(<ToastProvider><Consumer /></ToastProvider>);
clk("S"); E(S.getByText("saved")).toBeInTheDocument();
fireEvent.click(dis()); E(S.queryByText("saved")).toBeNull();
clk("W"); E(S.getByText("warn")).toBeInTheDocument();
for (const g of ["✓", "✕", "⚠", "ℹ"]) E(S.queryByText(g)).toBeNull();
fireEvent.click(dis());
await user.click(S.getByRole("button", { name: "E" }));
E(S.getByRole("region", { name: "Notifications" })).toHaveAttribute("aria-live", "polite");
E(S.getByRole("alert")).toHaveTextContent("failed");
dis().focus();
await user.keyboard("{Enter}");
E(S.queryByText("failed")).toBeNull();
clk("E"); E(S.getByText("failed")).toBeInTheDocument();
await new Promise((r) => setTimeout(r, 3200));
await waitFor(() => E(S.queryByText("failed")).toBeNull());
});
// AC-meta.fe-app-shell.12 AC-meta.fe-ia-nav.16
