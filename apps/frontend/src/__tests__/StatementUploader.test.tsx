import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import StatementUploader from "@/components/statements/StatementUploader";
import { fetchAiModels } from "@/lib/aiModels";
import { apiUpload } from "@/lib/api";
import { track, ANALYTICS_EVENTS } from "@/lib/analytics";

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

vi.mock("@/lib/analytics", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/analytics")>()),
  track: vi.fn(),
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

describe("AC3.5.3 StatementUploader model selection", () => {
  beforeEach(() => {
    vi.mocked(fetchAiModels).mockReset();
    vi.mocked(apiUpload).mockReset();
    vi.mocked(track).mockReset();
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

  it("AC8.4.1 hides AI model selection for CSV uploads and submits without model", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });

    render(<StatementUploader />);

    const fileInput = screen.getByLabelText(/drop files here or click to upload/i);
    const file = new File(["date,description,amount"], "statement.csv", { type: "text/csv" });
    await userEvent.upload(fileInput, file);

    expect(screen.queryByLabelText(/ai model/i)).not.toBeInTheDocument();
    expect(screen.getByText("CSV files are parsed directly")).toBeInTheDocument();
    expect(screen.getByText("No AI model needed.")).toBeInTheDocument();

    const uploadButton = screen.getByRole("button", { name: /upload & parse statement/i });
    await userEvent.click(uploadButton);

    await waitFor(() => {
      expect(apiUpload).toHaveBeenCalledTimes(1);
    });

    const formData = vi.mocked(apiUpload).mock.calls[0]?.[1] as FormData;
    expect(formData.get("file")).toBe(file);
    expect(formData.get("model")).toBeNull();
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

  it("handles model change and storage", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });

    render(<StatementUploader />);
    const select = await screen.findByLabelText(/ai model/i);
    // Wait for models to load (select starts disabled until fetchAiModels resolves)
    await waitFor(() => {
      expect(select).not.toBeDisabled();
    });
    await userEvent.selectOptions(select, "qwen/qwen-2.5-vl-7b-instruct:free");
    expect(select).toHaveValue("qwen/qwen-2.5-vl-7b-instruct:free");
    expect(localStorage.getItem("statement_model_v1")).toBe("qwen/qwen-2.5-vl-7b-instruct:free");
  });

  it("handles institution input change", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });

    render(<StatementUploader />);
    const input = screen.getByLabelText(/bank \/ institution/i);
    await userEvent.type(input, "DBS Bank");
    expect(input).toHaveValue("DBS Bank");
  });

  it("handles fetch AI models failure", async () => {
    vi.mocked(fetchAiModels).mockRejectedValue(new Error("Network Error"));
    render(<StatementUploader />);
    await screen.findByText("Unable to load AI models. Please try again.");
  });

  it("handles storage write error", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: () => {
        throw new Error("Quota exceeded");
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
    });
    render(<StatementUploader />);
    const select = await screen.findByLabelText(/ai model/i);
    // Wait for models to load (select starts disabled until fetchAiModels resolves)
    await waitFor(() => {
      expect(select).not.toBeDisabled();
    });
    await userEvent.selectOptions(select, "qwen/qwen-2.5-vl-7b-instruct:free");
    expect(warnSpy).toHaveBeenCalledWith(
      "[Storage] Failed to write statement_model_v1:",
      expect.any(Error),
    );
    vi.unstubAllGlobals();
    warnSpy.mockRestore();
  });

  it("test_AC8_13_48 falls back to the default model when storage reads fail", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("storage blocked");
      },
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
      key: vi.fn(),
      length: 0,
    });

    render(<StatementUploader />);

    const select = await screen.findByLabelText(/ai model/i);
    await waitFor(() => {
      expect(select).toHaveValue("google/gemini-3-flash-preview");
    });
    expect(warnSpy).toHaveBeenCalledWith(
      "[Storage] Failed to read statement_model_v1:",
      expect.any(Error),
    );

    vi.unstubAllGlobals();
    warnSpy.mockRestore();
  });

  it("test_AC8_13_48 removes invalid stored model ids and tolerates removal failures", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });
    localStorage.setItem("statement_model_v1", "obsolete-model");
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const removeSpy = vi.spyOn(localStorage, "removeItem").mockImplementation(() => {
      throw new Error("remove blocked");
    });

    render(<StatementUploader />);

    const select = await screen.findByLabelText(/ai model/i);
    await waitFor(() => {
      expect(select).toHaveValue("google/gemini-3-flash-preview");
    });
    expect(warnSpy).toHaveBeenCalledWith(
      "[Storage] Failed to remove statement_model_v1:",
      expect.any(Error),
    );

    removeSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("handles drag events", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });
    render(<StatementUploader />);
    const dropZone = screen.getByText(/drop files here or click to upload/i).closest('.card')!;
    fireEvent.dragOver(dropZone);
    expect(dropZone).toHaveClass("border-[var(--accent)]");
    fireEvent.dragLeave(dropZone);
    expect(dropZone).not.toHaveClass("border-[var(--accent)]");
  });

  it("includes institution in upload", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });
    render(<StatementUploader />);
    const input = screen.getByLabelText(/bank \/ institution/i);
    await userEvent.type(input, "DBS");
    const fileInput = screen.getByLabelText(/drop files here or click to upload/i);
    const file = new File(["data"], "statement.pdf", { type: "application/pdf" });
    await userEvent.upload(fileInput, file);
    const uploadButton = screen.getByRole("button", { name: /upload & parse statement/i });
    await userEvent.click(uploadButton);
    const formData = vi.mocked(apiUpload).mock.calls[0]?.[1] as FormData;
    expect(formData.get("institution")).toBe("DBS");
  });

  it("handles upload failure", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });
    vi.mocked(apiUpload).mockRejectedValue(new Error("Server Error"));
    render(<StatementUploader />);
    const fileInput = screen.getByLabelText(/drop files here or click to upload/i);
    const file = new File(["data"], "statement.pdf", { type: "application/pdf" });
    await userEvent.upload(fileInput, file);
    const uploadButton = screen.getByRole("button", { name: /upload & parse statement/i });
    await userEvent.click(uploadButton);
    await screen.findByText("Server Error");
  });

  it("AC8.4.1 rejects unsupported and oversized statement files before upload", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });

    render(<StatementUploader />);

    const fileInput = screen.getByLabelText(/drop files here or click to upload/i);
    fireEvent.change(fileInput, {
      target: { files: [new File(["data"], "statement.exe", { type: "application/octet-stream" })] },
    });
    expect(await screen.findByText("Invalid file type: .exe. Allowed: PDF, CSV, PNG, or JPG")).toBeInTheDocument();

    const hugeFile = new File([new Uint8Array(10 * 1024 * 1024 + 1)], "statement.pdf", { type: "application/pdf" });
    fireEvent.change(fileInput, { target: { files: [hugeFile] } });
    expect(await screen.findByText("File exceeds 10MB limit")).toBeInTheDocument();
    expect(apiUpload).not.toHaveBeenCalled();
  });

  it("AC19.15.3 statement uploader rejects csv and csv uploader rejects non-csv, each enforcing its own kind's extensions", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });

    const { unmount } = render(<StatementUploader kind="statement" />);
    fireEvent.change(screen.getByTestId("uploader-file-statement"), {
      target: { files: [new File(["a,b"], "data.csv", { type: "text/csv" })] },
    });
    expect(
      await screen.findByText("Invalid file type: .csv. Allowed: PDF, PNG, or JPG"),
    ).toBeInTheDocument();
    unmount();

    render(<StatementUploader kind="csv" />);
    const csvInput = screen.getByTestId("uploader-file-csv");
    fireEvent.change(csvInput, {
      target: { files: [new File(["data"], "statement.pdf", { type: "application/pdf" })] },
    });
    expect(
      await screen.findByText("Invalid file type: .pdf. Allowed: CSV"),
    ).toBeInTheDocument();

    fireEvent.change(csvInput, {
      target: { files: [new File(["a,b"], "data.csv", { type: "text/csv" })] },
    });
    expect(await screen.findByText("data.csv")).toBeInTheDocument();
  });

  it("AC8.4.1 requires a file and calls completion callback after successful upload", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });
    vi.mocked(apiUpload).mockResolvedValue({});
    const onUploadComplete = vi.fn();

    render(<StatementUploader onUploadComplete={onUploadComplete} />);

    const uploadButton = screen.getByRole("button", { name: /upload & parse statement/i });
    await userEvent.click(uploadButton);
    expect(await screen.findByText("Please select a file")).toBeInTheDocument();

    const fileInput = screen.getByLabelText(/drop files here or click to upload/i);
    const file = new File(["data"], "statement.pdf", { type: "application/pdf" });
    await userEvent.upload(fileInput, file);
    await userEvent.click(uploadButton);

    await waitFor(() => expect(apiUpload).toHaveBeenCalledWith("/api/statements/upload", expect.any(FormData)));
    expect(onUploadComplete).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/drop files here or click to upload/i)).toBeInTheDocument();
  });

  it("AC8.4.1 accepts dropped statement files", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });

    render(<StatementUploader />);

    const dropZone = screen.getByText(/drop files here or click to upload/i).closest(".card")!;
    const file = new File(["data"], "statement.png", { type: "image/png" });
    fireEvent.drop(dropZone, { dataTransfer: { files: [file] } });

    expect(await screen.findByText("statement.png")).toBeInTheDocument();
  });

  it("AC22.18.3 tracks UPLOAD_STARTED and UPLOAD_SUCCEEDED with non-PII props on success", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });
    vi.mocked(apiUpload).mockResolvedValue({});

    render(<StatementUploader />);

    const fileInput = screen.getByLabelText(/drop files here or click to upload/i);
    const file = new File(["data"], "statement.pdf", { type: "application/pdf" });
    await userEvent.upload(fileInput, file);
    await userEvent.click(screen.getByRole("button", { name: /upload & parse statement/i }));

    await waitFor(() => expect(apiUpload).toHaveBeenCalledTimes(1));

    expect(vi.mocked(track)).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.UPLOAD_STARTED,
      expect.objectContaining({ is_csv: false }),
    );
    expect(vi.mocked(track)).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.UPLOAD_SUCCEEDED,
      expect.objectContaining({ is_csv: false }),
    );

    // No PII (filename) is forwarded to analytics.
    for (const call of vi.mocked(track).mock.calls) {
      expect(JSON.stringify(call[1] ?? {})).not.toContain("statement.pdf");
    }
  });

  it("AC22.18.3 tracks UPLOAD_FAILED with an error category on failure", async () => {
    vi.mocked(fetchAiModels).mockResolvedValue({
      default_model: "google/gemini-3-flash-preview",
      fallback_models: [],
      models: baseModels,
    });
    vi.mocked(apiUpload).mockRejectedValue(new Error("Server Error"));

    render(<StatementUploader />);

    const fileInput = screen.getByLabelText(/drop files here or click to upload/i);
    const file = new File(["data"], "statement.pdf", { type: "application/pdf" });
    await userEvent.upload(fileInput, file);
    await userEvent.click(screen.getByRole("button", { name: /upload & parse statement/i }));

    await screen.findByText("Server Error");

    expect(vi.mocked(track)).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.UPLOAD_FAILED,
      expect.objectContaining({ error_category: "error" }),
    );
    // The raw error message must not leak into analytics props.
    for (const call of vi.mocked(track).mock.calls) {
      expect(JSON.stringify(call[1] ?? {})).not.toContain("Server Error");
    }
  });
});
