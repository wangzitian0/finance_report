import { describe, it, expect, vi, beforeEach } from "vitest";
import { fetchAiModels } from "../lib/aiModels";
import * as api from "../lib/api";

vi.mock("../lib/api", () => ({
    apiFetch: vi.fn(),
}));

describe("fetchAiModels", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("AC16.8.1 calls /api/ai/models with no query when no options provided", async () => {
        const mockResponse = {
            default_model: "google/gemini-flash",
            fallback_models: [],
            models: [],
        };
        vi.mocked(api.apiFetch).mockResolvedValue(mockResponse);

        await fetchAiModels();

        expect(api.apiFetch).toHaveBeenCalledWith("/api/ai/models");
    });

    it("AC16.8.2 appends modality query param when provided", async () => {
        vi.mocked(api.apiFetch).mockResolvedValue({ default_model: "", fallback_models: [], models: [] });

        await fetchAiModels({ modality: "vision" });

        expect(api.apiFetch).toHaveBeenCalledWith("/api/ai/models?modality=vision");
    });

    it("AC16.8.3 appends free_only=true when freeOnly is set", async () => {
        vi.mocked(api.apiFetch).mockResolvedValue({ default_model: "", fallback_models: [], models: [] });

        await fetchAiModels({ freeOnly: true });

        expect(api.apiFetch).toHaveBeenCalledWith("/api/ai/models?free_only=true");
    });

    it("AC16.8.3 combines modality and free_only params", async () => {
        vi.mocked(api.apiFetch).mockResolvedValue({ default_model: "", fallback_models: [], models: [] });

        await fetchAiModels({ modality: "text", freeOnly: true });

        expect(api.apiFetch).toHaveBeenCalledWith("/api/ai/models?modality=text&free_only=true");
    });
});
