import { describe, expect, it, vi } from "vitest";

import AccountsProcessingAliasPage from "@/app/(main)/accounts/processing/page";
import StatementUploadAliasPage from "@/app/(main)/statements/upload/page";

const redirectMock = vi.fn();

vi.mock("next/navigation", () => ({
  redirect: (path: string) => redirectMock(path),
}));

describe("workflow action route aliases", () => {
  it("AC19.4.3 AC19.6.6 keeps workflow upload action href reachable", () => {
    StatementUploadAliasPage();

    expect(redirectMock).toHaveBeenCalledWith("/statements");
  });

  it("AC19.5.4 AC19.6.6 keeps Processing readiness blocker href reachable", () => {
    AccountsProcessingAliasPage();

    expect(redirectMock).toHaveBeenCalledWith("/processing");
  });
});
