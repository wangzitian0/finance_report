import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiOperation } from "@/lib/api";
import { makeFetchMock } from "./helpers/shellTestFixtures";

describe("LLM api wrappers (EPIC-023 PR4)", () => {
  beforeEach(() => { localStorage.clear(); vi.unstubAllGlobals(); });
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    ["get_config_status_llm_config_status_get", undefined, 200, { configured: true }, "GET", /\/api\/llm\/config\/status$/],
    ["list_providers_llm_providers_get", undefined, 200, { providers: [] }, "GET", /\/api\/llm\/providers$/],
    ["create_provider_llm_providers_post", { body: { label: "OR", protocol: "openrouter-compatible", api_key: "k", api_base: "https://openrouter.ai/api/v1" } }, 201, { id: "p1" }, "POST", /\/api\/llm\/providers$/],
    ["delete_provider_llm_providers__provider_id__delete", { path: { provider_id: "p1" } }, 200, { id: "p1", deleted: true }, "DELETE", /\/api\/llm\/providers\/p1$/],
    ["get_catalog_llm_catalog_get", undefined, 200, { models: [] }, "GET", /\/api\/llm\/catalog$/],
    ["get_catalog_llm_catalog_get", { query: { modality: "image", free_only: true } }, 200, { models: [] }, "GET", /modality=image.*free_only=true/],
    ["get_catalog_llm_catalog_get", { query: { free_only: false } }, 200, { models: [] }, "GET", /free_only=false/],
    ["get_scenes_llm_scenes_get", undefined, 200, { bindings: [] }, "GET", /\/api\/llm\/scenes$/],
    ["put_scenes_llm_scenes_put", { body: { bindings: [] } }, 200, { bindings: [] }, "PUT", /\/api\/llm\/scenes$/],
  ] as const)("dispatches %s", async (op, req, status, body, method, urlRe) => {
    const f = makeFetchMock(status, body);
    vi.stubGlobal("fetch", f);
    expect(await apiOperation(op as never, req as never)).toEqual(body);
    expect(String(f.mock.calls[0][0])).toMatch(urlRe);
    expect(f.mock.calls[0][1]?.method ?? "GET").toBe(method);
  });
});
