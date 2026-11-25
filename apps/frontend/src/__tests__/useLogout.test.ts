import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import React, { type ReactNode } from "react";
import { expect, it, vi } from "vitest";
import { useBaseCurrency } from "@/hooks/useBaseCurrency";
import { useLogout } from "@/hooks/useLogout";
import { apiOperation } from "@/lib/api";
import { clearUser } from "@/lib/auth";
import { createAppQueryClient } from "@/lib/queryClient";
const push = vi.fn(),
  api = vi.mocked(apiOperation),
  E = expect;
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
vi.mock("@/lib/auth", () => ({ clearUser: vi.fn() }));
it("coalesces logout, clears cache, isolates user (#2553)", async () => {
  let done!: () => void;
  api.mockReturnValue(
    new Promise<void>((r) => {
      done = r;
    }),
  );
  const { result } = renderHook(() => useLogout());
  let p!: Promise<void>;
  act(() => {
    p = result.current.handleLogout();
    void result.current.handleLogout();
  });
  E(api).toHaveBeenCalledTimes(1);
  E(clearUser).not.toHaveBeenCalled();
  await act(async () => {
    done();
    await p;
  });
  E(clearUser).toHaveBeenCalledOnce();
  E(push).toHaveBeenCalledWith("/login");
  api.mockResolvedValue(undefined as never);
  const qc = createAppQueryClient(),
    wrapper = ({ children }: { children: ReactNode }) =>
      React.createElement(QueryClientProvider, { client: qc }, children);
  qc.setQueryData(["user-settings", "base-currency"], { base_currency: "USD" });
  qc.setQueryData(["accounts"], [{ id: "a1", name: "S" }]);
  let atPush = -1;
  push.mockImplementationOnce(() => {
    atPush = qc.getQueryCache().getAll().length;
  });
  const u1 = renderHook(() => useBaseCurrency(), { wrapper });
  E(u1.result.current.baseCurrency).toBe("USD");
  u1.unmount();
  const lo = renderHook(() => useLogout(), { wrapper });
  await act(async () => {
    await lo.result.current.handleLogout();
  });
  lo.unmount();
  E([
    atPush,
    qc.getQueryData(["user-settings", "base-currency"]),
    qc.getQueryData(["accounts"]),
  ]).toEqual([0, undefined, undefined]);
  E(push).toHaveBeenCalledWith("/login");
  let res2!: (v: { base_currency: string }) => void;
  api.mockImplementation((op: string) =>
    op === "get_base_currency_users_me_settings_base_currency_get"
      ? (new Promise((r) => {
          res2 = r;
        }) as never)
      : Promise.resolve(undefined as never),
  );
  const u2 = renderHook(() => useBaseCurrency(), { wrapper });
  E(u2.result.current.baseCurrency).toBe("SGD");
  await act(async () => {
    res2({ base_currency: "EUR" });
  });
  await waitFor(() => E(u2.result.current.baseCurrency).toBe("EUR"));
});
// AC-identity.fe-auth.15
