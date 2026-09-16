import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useLogout } from "@/hooks/useLogout";
import { apiOperation } from "@/lib/api-client";
import { clearUser } from "@/lib/auth";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api-client", () => ({ apiOperation: vi.fn() }));
vi.mock("@/lib/auth", () => ({ clearUser: vi.fn() }));

// AC-identity.fe-auth.15
it("coalesces duplicate logout actions while server expiration is pending", async () => {
  let complete!: () => void;
  vi.mocked(apiOperation).mockReturnValue(new Promise<void>((resolve) => { complete = resolve; }));
  const { result } = renderHook(() => useLogout());
  let first!: Promise<void>;
  act(() => {
    first = result.current.handleLogout();
    void result.current.handleLogout();
  });
  expect(apiOperation).toHaveBeenCalledTimes(1);
  expect(clearUser).not.toHaveBeenCalled();
  await act(async () => { complete(); await first; });
  expect(clearUser).toHaveBeenCalledOnce();
  expect(push).toHaveBeenCalledWith("/login");
});
