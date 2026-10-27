import { describe, it, expect, vi, beforeEach } from "vitest";
import { fetchAiModels } from "../lib/aiModels";
import { apiOperation } from "../lib/api-client";

vi.mock("../lib/api-client", () => ({
    apiOperation: vi.fn(),
}));

const emptyCatalog = { models: [] };

describe("fetchAiModels", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    // AC-llm.fe-ai-models-catalog.1
    it("AC16.8.1 calls /api/llm/catalog with no query when no options provided", async () => {
        vi.mocked(apiOperation).mockResolvedValue(emptyCatalog as any);

        await fetchAiModels();

        expect(apiOperation).toHaveBeenCalledWith("get_catalog_llm_catalog_get", {
            query: { modality: undefined, free_only: undefined },
        });
    });

    // AC-llm.fe-ai-models-catalog.2
    it("AC16.8.2 appends modality query param when provided", async () => {
        vi.mocked(apiOperation).mockResolvedValue(emptyCatalog as any);

        await fetchAiModels({ modality: "image" });

        expect(apiOperation).toHaveBeenCalledWith("get_catalog_llm_catalog_get", {
            query: { modality: "image", free_only: undefined },
        });
    });

    // AC-llm.fe-ai-models-catalog.3
    it("AC16.8.3 appends free_only=true when freeOnly is set", async () => {
        vi.mocked(apiOperation).mockResolvedValue(emptyCatalog as any);

        await fetchAiModels({ freeOnly: true });

        expect(apiOperation).toHaveBeenCalledWith("get_catalog_llm_catalog_get", {
            query: { modality: undefined, free_only: true },
        });
    });

    it("AC16.8.3 combines modality and free_only params", async () => {
        vi.mocked(apiOperation).mockResolvedValue(emptyCatalog as any);

        await fetchAiModels({ modality: "text", freeOnly: true });

        expect(apiOperation).toHaveBeenCalledWith("get_catalog_llm_catalog_get", {
            query: { modality: "text", free_only: true },
        });
    });

    it("AC16.8.3 adapts the catalogue response into the legacy model-list shape", async () => {
        vi.mocked(apiOperation).mockResolvedValue({
            models: [
                {
                    id: "google/gemini-flash",
                    provider_id: "openrouter",
                    modalities: ["text", "image"],
                    is_free: true,
                    input_price_per_mtok: null,
                    output_price_per_mtok: null,
                    supports_reasoning: false,
                },
                {
                    id: "anthropic/claude-3",
                    provider_id: "openrouter",
                    modalities: ["text"],
                    is_free: false,
                    input_price_per_mtok: "3",
                    output_price_per_mtok: "15",
                    supports_reasoning: true,
                },
            ],
        } as any);

        const result = await fetchAiModels({ modality: "image" });

        // default_model is the first catalogue entry's id.
        expect(result.default_model).toBe("google/gemini-flash");
        expect("fallback_models" in result).toBe(false);
        // Each model is mapped: name = id.
        expect(result.models).toEqual([
            {
                id: "google/gemini-flash",
                name: "google/gemini-flash",
                is_free: true,
            },
            {
                id: "anthropic/claude-3",
                name: "anthropic/claude-3",
                is_free: false,
            },
        ]);
    });

    it("AC16.8.3 returns empty default_model when the catalogue is empty", async () => {
        vi.mocked(apiOperation).mockResolvedValue(emptyCatalog as any);

        const result = await fetchAiModels();

        expect(result.default_model).toBe("");
        expect(result.models).toEqual([]);
    });
});
