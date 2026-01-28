import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import StatementUploader from "@/components/statements/StatementUploader";
import { fetchAiModels } from "@/lib/aiModels";
import { apiUpload } from "@/lib/api";

vi.mock("@/lib/aiModels", () => ({
  fetchAiModels: vi.fn(),
}));

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({
    showToast: vi.fn(),
  }),
}));

vi.mock("@/lib/api", () => ({
  apiUpload: vi.fn(),
}));

const baseModels = [
  {
    id: "google/gemini-3-flash-preview",
    name: "Gemini 3 Flash",
    is_free: true,
    input_modalities: ["image"],
    pricing: {},
  },
  {
    id: "qwen/qwen-2.5-vl-7b-instruct:free",
    name: "Qwen 2.5 VL 7B",
    is_free: true,
    input_modalities: ["image"],
    pricing: {},
  },
];

describe("StatementUploader model selection", () => {
  beforeEach(() => {
    vi.mocked(fetchAiModels).mockReset();
    vi.mocked(apiUpload).mockReset();
    if (!globalThis.localStorage || typeof globalThis.localStorage.clear !== "function") {
      const store = new Map<string, string>();
      globalThis.localStorage = {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => {
          store.set(key, String(value));
        },
        removeItem: (key: string) => {
          store.delete(key);
        },
        clear: () => {
          store.clear();
        },
        key: (index: number) => Array.from(store.keys())[index] ?? null,
        get length() {
          return store.size;
        },
      } as Storage;
    }
    globalThis.localStorage.clear();
  });

  it("prefers stored user selection when valid", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });

    localStorage.setItem("statement_model_v1", "qwen/qwen-2.5-vl-7b-instruct:free");

    render(<StatementUploader />);

    const select = await screen.findByLabelText(/ai model/i);
    await waitFor(() => {
      expect(select).toHaveValue("qwen/qwen-2.5-vl-7b-instruct:free");
    });

    const fileInput = screen.getByLabelText(/drop files here or click to upload/i);
    const file = new File(["data"], "statement.pdf", { type: "application/pdf" });
    await userEvent.upload(fileInput, file);

    const uploadButton = screen.getByRole("button", { name: /upload & parse statement/i });
    await userEvent.click(uploadButton);

    await waitFor(() => {
      expect(apiUpload).toHaveBeenCalledTimes(1);
    });

    const formData = vi.mocked(apiUpload).mock.calls[0]?.[1] as FormData;
    expect(formData.get("model")).toBe("qwen/qwen-2.5-vl-7b-instruct:free");
  });

  it("uses default model when no stored selection exists", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });

    render(<StatementUploader />);

    const select = await screen.findByLabelText(/ai model/i);
    await waitFor(() => {
      expect(select).toHaveValue("google/gemini-3-flash-preview");
    });
  });

  it("errors when default model is not in the filtered catalog", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: [baseModels[1]],
    });

    render(<StatementUploader />);

    await screen.findByText("We couldn't find a default AI model. Refresh and try again.");

    const fileInput = screen.getByLabelText(/drop files here or click to upload/i);
    const file = new File(["data"], "statement.pdf", { type: "application/pdf" });
    await userEvent.upload(fileInput, file);

    const uploadButton = screen.getByRole("button", { name: /upload & parse statement/i });
    await userEvent.click(uploadButton);

    await screen.findByText("Please select an AI model");
    expect(apiUpload).not.toHaveBeenCalled();
  });
});
