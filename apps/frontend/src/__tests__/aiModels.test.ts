import { describe, it, expect, vi, beforeEach } from "vitest";
import { fetchAiModels } from "../lib/aiModels";
import * as api from "../lib/api";

vi.mock("../lib/api", () => ({
    apiFetch: vi.fn(),
}));

const emptyCatalog = { models: [] };

describe("fetchAiModels", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    // AC-llm.fe-ai-models-catalog.1
    it("AC16.8.1 calls /api/llm/catalog with no query when no options provided", async () => {
        vi.mocked(api.apiFetch).mockResolvedValue(emptyCatalog);

        await fetchAiModels();

        expect(api.apiFetch).toHaveBeenCalledWith("/api/llm/catalog");
    });

    // AC-llm.fe-ai-models-catalog.2
    it("AC16.8.2 appends modality query param when provided", async () => {
        vi.mocked(api.apiFetch).mockResolvedValue(emptyCatalog);

        await fetchAiModels({ modality: "image" });

        expect(api.apiFetch).toHaveBeenCalledWith("/api/llm/catalog?modality=image");
    });

    // AC-llm.fe-ai-models-catalog.3
    it("AC16.8.3 appends free_only=true when freeOnly is set", async () => {
        vi.mocked(api.apiFetch).mockResolvedValue(emptyCatalog);

        await fetchAiModels({ freeOnly: true });

        expect(api.apiFetch).toHaveBeenCalledWith("/api/llm/catalog?free_only=true");
    });

    it("AC16.8.3 combines modality and free_only params", async () => {
        vi.mocked(api.apiFetch).mockResolvedValue(emptyCatalog);

        await fetchAiModels({ modality: "text", freeOnly: true });

        expect(api.apiFetch).toHaveBeenCalledWith("/api/llm/catalog?modality=text&free_only=true");
    });

    it("AC16.8.3 adapts the catalogue response into the legacy model-list shape", async () => {
        vi.mocked(api.apiFetch).mockResolvedValue({
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
        });

        const result = await fetchAiModels({ modality: "image" });

        // default_model is the first catalogue entry's id.
        expect(result.default_model).toBe("google/gemini-flash");
        // fallback_models are the remaining ids.
        expect(result.fallback_models).toEqual(["anthropic/claude-3"]);
        // Each model is mapped: name = id, input_modalities from modalities, empty pricing.
        expect(result.models).toEqual([
            {
                id: "google/gemini-flash",
                name: "google/gemini-flash",
                is_free: true,
                input_modalities: ["text", "image"],
                pricing: {},
            },
            {
                id: "anthropic/claude-3",
                name: "anthropic/claude-3",
                is_free: false,
                input_modalities: ["text"],
                pricing: {},
            },
        ]);
    });

    it("AC16.8.3 returns empty default_model when the catalogue is empty", async () => {
        vi.mocked(api.apiFetch).mockResolvedValue(emptyCatalog);

        const result = await fetchAiModels();

        expect(result.default_model).toBe("");
        expect(result.fallback_models).toEqual([]);
        expect(result.models).toEqual([]);
    });
});
