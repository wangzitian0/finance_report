import { describe, expect, it, vi } from "vitest";

import AccountsProcessingAliasPage from "@/app/(main)/accounts/processing/page";

const redirectMock = vi.fn();

vi.mock("next/navigation", () => ({
  redirect: (path: string) => redirectMock(path),
}));

describe("workflow action route aliases", () => {
  it("AC19.5.4 keeps Processing readiness blocker href reachable", () => {
    AccountsProcessingAliasPage();

    expect(redirectMock).toHaveBeenCalledWith("/processing");
  });
});
