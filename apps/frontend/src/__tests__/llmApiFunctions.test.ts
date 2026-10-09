import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// localStorage mock (must be set before importing api module)
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();
vi.stubGlobal("localStorage", localStorageMock);

function makeFetchMock(
  status: number,
  body: unknown,
  headers: Record<string, string> = {}
) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    text: () =>
      Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)),
    json: () => Promise.resolve(body),
    headers: { get: (name: string) => headers[name] ?? null },
  });
}

describe("LLM api wrappers (EPIC-023 PR4)", () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.unstubAllGlobals();
    vi.stubGlobal("localStorage", localStorageMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.stubGlobal("localStorage", localStorageMock);
  });

  it("get_config_status_llm_config_status_get GETs /api/llm/config/status", async () => {
    const fetchMock = makeFetchMock(200, { configured: true });
    vi.stubGlobal("fetch", fetchMock);

    const { apiOperation } = await import("@/lib/api-client");
    const result = await apiOperation("get_config_status_llm_config_status_get");

    expect(result).toEqual({ configured: true });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/llm\/config\/status/);
    expect(fetchMock.mock.calls[0][1]?.method ?? "GET").toBe("GET");
  });

  it("list_providers_llm_providers_get GETs /api/llm/providers", async () => {
    const fetchMock = makeFetchMock(200, { providers: [] });
    vi.stubGlobal("fetch", fetchMock);

    const { apiOperation } = await import("@/lib/api-client");
    const result = await apiOperation("list_providers_llm_providers_get");

    expect(result).toEqual({ providers: [] });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/llm\/providers/);
  });

  it("create_provider_llm_providers_post POSTs the provider body", async () => {
    const created = {
      id: "p1",
      label: "OR",
      protocol: "openrouter-compatible",
      api_base: "https://openrouter.ai/api/v1",
      has_api_key: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    const fetchMock = makeFetchMock(201, created);
    vi.stubGlobal("fetch", fetchMock);

    const { apiOperation } = await import("@/lib/api-client");
    const result = await apiOperation("create_provider_llm_providers_post", {
      body: {
        label: "OR",
        protocol: "openrouter-compatible",
        api_key: "secret",
        api_base: "https://openrouter.ai/api/v1",
      },
    });

    expect(result).toEqual(created);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/llm\/providers/);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      label: "OR",
      protocol: "openrouter-compatible",
      api_key: "secret",
      api_base: "https://openrouter.ai/api/v1",
    });
  });

  it("delete_provider_llm_providers__provider_id__delete DELETEs /api/llm/providers/{id}", async () => {
    // The backend returns 200 with a JSON confirmation body ({id, deleted}).
    const fetchMock = makeFetchMock(200, { id: "p1", deleted: true });
    vi.stubGlobal("fetch", fetchMock);

    const { apiOperation } = await import("@/lib/api-client");
    await apiOperation("delete_provider_llm_providers__provider_id__delete", {
      path: { provider_id: "p1" },
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/llm\/providers\/p1/);
    expect(init.method).toBe("DELETE");
  });

  it("get_catalog_llm_catalog_get GETs without query when no options", async () => {
    const fetchMock = makeFetchMock(200, { models: [] });
    vi.stubGlobal("fetch", fetchMock);

    const { apiOperation } = await import("@/lib/api-client");
    await apiOperation("get_catalog_llm_catalog_get");

    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/llm\/catalog$/);
  });

  it("get_catalog_llm_catalog_get builds a query string from modality and free_only", async () => {
    const fetchMock = makeFetchMock(200, { models: [] });
    vi.stubGlobal("fetch", fetchMock);

    const { apiOperation } = await import("@/lib/api-client");
    await apiOperation("get_catalog_llm_catalog_get", {
      query: { modality: "image" as any, free_only: true },
    });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("modality=image");
    expect(url).toContain("free_only=true");
  });

  it("get_catalog_llm_catalog_get includes free_only=false explicitly when set", async () => {
    const fetchMock = makeFetchMock(200, { models: [] });
    vi.stubGlobal("fetch", fetchMock);

    const { apiOperation } = await import("@/lib/api-client");
    await apiOperation("get_catalog_llm_catalog_get", {
      query: { free_only: false },
    });

    expect(String(fetchMock.mock.calls[0][0])).toContain("free_only=false");
  });

  it("get_scenes_llm_scenes_get GETs /api/llm/scenes", async () => {
    const fetchMock = makeFetchMock(200, { bindings: [] });
    vi.stubGlobal("fetch", fetchMock);

    const { apiOperation } = await import("@/lib/api-client");
    const result = await apiOperation("get_scenes_llm_scenes_get");

    expect(result).toEqual({ bindings: [] });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/llm\/scenes/);
  });

  it("put_scenes_llm_scenes_put PUTs the bindings", async () => {
    const body = { bindings: [] };
    const fetchMock = makeFetchMock(200, body);
    vi.stubGlobal("fetch", fetchMock);

    const { apiOperation } = await import("@/lib/api-client");
    const result = await apiOperation("put_scenes_llm_scenes_put", { body });

    expect(result).toEqual(body);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/llm\/scenes/);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual(body);
  });
});
