import { describe, expect, it } from "vitest"; import { apiOperation } from "@/lib/api"; describe("generated operation request contract", () => { it("AC-meta.public-boundary.3 requires path and body inputs at compile time", () => { if (false) { void apiOperation("health_health_get"); void apiOperation("delete_account_accounts__account_id__delete", { path: { account_id: "account-id" }, });
// @ts-expect-error required OpenAPI path input cannot be omitted
void apiOperation("delete_account_accounts__account_id__delete");
// @ts-expect-error required OpenAPI request body cannot be omitted
void apiOperation("create_account_accounts_post"); }; expect(true).toBe(true); }); });
