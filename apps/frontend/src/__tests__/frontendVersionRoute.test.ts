import { afterEach, describe, expect, it } from "vitest";

import { GET } from "@/app/frontend-version.json/route";

describe("frontend version route", () => {
  const originalGitSha = process.env.GIT_COMMIT_SHA;

  afterEach(() => {
    if (originalGitSha === undefined) {
      delete process.env.GIT_COMMIT_SHA;
    } else {
      process.env.GIT_COMMIT_SHA = originalGitSha;
    }
  });

  it("AC8.13.67 exposes the frontend git sha for PR preview readiness", async () => {
    process.env.GIT_COMMIT_SHA = "test-sha";

    const response = await GET();
    const payload = await response.json();

    expect(payload).toEqual({
      git_sha: "test-sha",
      version: "test-sha",
    });
  });
});
