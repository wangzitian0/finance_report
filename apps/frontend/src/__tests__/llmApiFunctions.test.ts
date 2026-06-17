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

  it("fetchLlmConfigStatus GETs /api/llm/config/status", async () => {
    const fetchMock = makeFetchMock(200, { configured: true });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchLlmConfigStatus } = await import("../lib/api");
    const result = await fetchLlmConfigStatus();

    expect(result).toEqual({ configured: true });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/llm\/config\/status/);
    expect(fetchMock.mock.calls[0][1]?.method ?? "GET").toBe("GET");
  });

  it("fetchLlmProviders GETs /api/llm/providers", async () => {
    const fetchMock = makeFetchMock(200, { providers: [] });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchLlmProviders } = await import("../lib/api");
    const result = await fetchLlmProviders();

    expect(result).toEqual({ providers: [] });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/llm\/providers/);
  });

  it("createLlmProvider POSTs the provider body", async () => {
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

    const { createLlmProvider } = await import("../lib/api");
    const result = await createLlmProvider({
      label: "OR",
      protocol: "openrouter-compatible",
      api_key: "secret",
      api_base: "https://openrouter.ai/api/v1",
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

  it("deleteLlmProvider DELETEs /api/llm/providers/{id}", async () => {
    // The backend returns 200 with a JSON confirmation body ({id, deleted}).
    const fetchMock = makeFetchMock(200, { id: "p1", deleted: true });
    vi.stubGlobal("fetch", fetchMock);

    const { deleteLlmProvider } = await import("../lib/api");
    await deleteLlmProvider("p1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/llm\/providers\/p1/);
    expect(init.method).toBe("DELETE");
  });

  it("fetchLlmCatalog GETs without query when no options", async () => {
    const fetchMock = makeFetchMock(200, { models: [] });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchLlmCatalog } = await import("../lib/api");
    await fetchLlmCatalog();

    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/llm\/catalog$/);
  });

  it("fetchLlmCatalog builds a query string from modality and freeOnly", async () => {
    const fetchMock = makeFetchMock(200, { models: [] });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchLlmCatalog } = await import("../lib/api");
    await fetchLlmCatalog({ modality: "image", freeOnly: true });

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("modality=image");
    expect(url).toContain("free_only=true");
  });

  it("fetchLlmCatalog includes free_only=false explicitly when set", async () => {
    const fetchMock = makeFetchMock(200, { models: [] });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchLlmCatalog } = await import("../lib/api");
    await fetchLlmCatalog({ freeOnly: false });

    expect(String(fetchMock.mock.calls[0][0])).toContain("free_only=false");
  });

  it("fetchLlmScenes GETs /api/llm/scenes", async () => {
    const fetchMock = makeFetchMock(200, { bindings: [] });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchLlmScenes } = await import("../lib/api");
    const result = await fetchLlmScenes();

    expect(result).toEqual({ bindings: [] });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/llm\/scenes/);
  });

  it("putLlmScenes PUTs the bindings", async () => {
    const body = { bindings: [] };
    const fetchMock = makeFetchMock(200, body);
    vi.stubGlobal("fetch", fetchMock);

    const { putLlmScenes } = await import("../lib/api");
    const result = await putLlmScenes(body);

    expect(result).toEqual(body);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/llm\/scenes/);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual(body);
  });
});
