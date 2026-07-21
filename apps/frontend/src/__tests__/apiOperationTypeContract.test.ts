import { describe, expect, it } from "vitest";

import { apiOperation } from "@/lib/api-client";

describe("generated operation request contract", () => {
  it("AC-meta.public-boundary.3 requires path and body inputs at compile time", () => {
    if (false) {
      void apiOperation("health_check_health_get");
      void apiOperation("get_account_accounts__account_id__get", {
        path: { account_id: "account-id" },
      });

      // @ts-expect-error required OpenAPI path input cannot be omitted
      void apiOperation("get_account_accounts__account_id__get");
      // @ts-expect-error required OpenAPI request body cannot be omitted
      void apiOperation("create_account_accounts_post");
    }

    expect(true).toBe(true);
  });
});
