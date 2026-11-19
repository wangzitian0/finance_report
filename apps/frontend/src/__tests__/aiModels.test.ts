import { beforeEach, expect, it, vi } from "vitest";
import { fetchAiModels } from "../lib/aiModels";
import { apiOperation } from "../lib/api";
vi.mock("../lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation);
beforeEach(() => vi.clearAllMocks());
it.each([
  [undefined, { modality: undefined, free_only: undefined }],
  [{ modality: "image" }, { modality: "image", free_only: undefined }],
  [{ freeOnly: true }, { modality: undefined, free_only: true }],
  [{ modality: "text", freeOnly: true }, { modality: "text", free_only: true }],
])("AC16.8.1 AC16.8.2 AC16.8.3 query %j", async (opts, query) => {
  api.mockResolvedValue({ models: [] } as any);
  expect(await fetchAiModels(opts)).toMatchObject({ default_model: "", models: [] });
  expect(api).toHaveBeenCalledWith("get_catalog_llm_catalog_get", { query });
});
it("AC16.8.3 adapts catalogue response", async () => {
  api.mockResolvedValue({ models: [{ id: "google/gemini-flash", provider_id: "openrouter", modalities: ["text", "image"], is_free: true, input_price_per_mtok: null, output_price_per_mtok: null, supports_reasoning: false }, { id: "anthropic/claude-3", provider_id: "openrouter", modalities: ["text"], is_free: false, input_price_per_mtok: "3", output_price_per_mtok: "15", supports_reasoning: true }] } as any);
  const res = await fetchAiModels({ modality: "image" });
  expect(res.default_model).toBe("google/gemini-flash");
  expect("fallback_models" in res).toBe(false);
  expect(res.models).toEqual([{ id: "google/gemini-flash", name: "google/gemini-flash", is_free: true }, { id: "anthropic/claude-3", name: "anthropic/claude-3", is_free: false }]);
});
// AC-llm.fe-ai-models-catalog.1 AC-llm.fe-ai-models-catalog.2 AC-llm.fe-ai-models-catalog.3
