import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LlmSettingsPage from "@/app/(main)/settings/llm/page";
import {
  createLlmProvider,
  deleteLlmProvider,
  fetchLlmCatalog,
  fetchLlmProviders,
  fetchLlmScenes,
  putLlmScenes,
} from "@/lib/api";

vi.mock("@/lib/api", () => ({
  createLlmProvider: vi.fn(),
  deleteLlmProvider: vi.fn(),
  fetchLlmCatalog: vi.fn(),
  fetchLlmProviders: vi.fn(),
  fetchLlmScenes: vi.fn(),
  putLlmScenes: vi.fn(),
}));

const showToast = vi.fn();
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast }),
}));

const mockedProviders = vi.mocked(fetchLlmProviders);
const mockedScenes = vi.mocked(fetchLlmScenes);
const mockedCatalog = vi.mocked(fetchLlmCatalog);
const mockedPut = vi.mocked(putLlmScenes);
const mockedDelete = vi.mocked(deleteLlmProvider);
const mockedCreate = vi.mocked(createLlmProvider);

const PROVIDER = {
  id: "prov-1",
  label: "OpenRouter",
  protocol: "openrouter-compatible" as const,
  api_base: "https://openrouter.ai/api/v1",
  has_api_key: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const MODEL = {
  id: "openrouter/auto",
  provider_id: "prov-1",
  modalities: ["text" as const],
  is_free: true,
  input_price_per_mtok: null,
  output_price_per_mtok: null,
  supports_reasoning: true,
};

function primeHappyLoad() {
  mockedProviders.mockResolvedValue({ providers: [PROVIDER] });
  mockedCatalog.mockResolvedValue({ models: [MODEL] });
  mockedScenes.mockResolvedValue({
    bindings: [
      {
        scene: "advisor.chat",
        provider_id: "prov-1",
        model: "openrouter/auto",
        reasoning: "low",
        prefer_free: true,
        fallback_model_ids: ["fallback-1"],
        max_tokens: null,
      },
    ],
  });
}

beforeEach(() => {
  showToast.mockReset();
  mockedProviders.mockReset();
  mockedScenes.mockReset();
  mockedCatalog.mockReset();
  mockedPut.mockReset();
  mockedDelete.mockReset();
  mockedCreate.mockReset();
});

describe("LlmSettingsPage (EPIC-023 PR4)", () => {
  it("shows a loading state then the loaded scenes and providers", async () => {
    primeHappyLoad();
    render(<LlmSettingsPage />);

    expect(screen.getByText("Loading LLM settings...")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("LLM Models")).toBeInTheDocument());

    // All five scenes are listed.
    expect(screen.getByText("Extraction · OCR")).toBeInTheDocument();
    expect(screen.getByText("Advisor · Chat")).toBeInTheDocument();
    expect(screen.getByText("Statement · Summary")).toBeInTheDocument();

    // The existing binding is hydrated into its scene row.
    expect(screen.getAllByLabelText("Model")).toHaveLength(5);
    expect(screen.getByDisplayValue("openrouter/auto")).toBeInTheDocument();

    // Provider list renders (the delete button is unique to the list item).
    expect(
      screen.getByRole("button", { name: /Delete provider OpenRouter/i })
    ).toBeInTheDocument();
  });

  it("shows a load error when fetching fails", async () => {
    mockedProviders.mockRejectedValue(new Error("Load failed"));
    mockedScenes.mockResolvedValue({ bindings: [] });
    mockedCatalog.mockResolvedValue({ models: [] });
    render(<LlmSettingsPage />);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Load failed")
    );
  });

  it("renders an empty-providers hint when none are configured", async () => {
    mockedProviders.mockResolvedValue({ providers: [] });
    mockedScenes.mockResolvedValue({ bindings: [] });
    mockedCatalog.mockResolvedValue({ models: [] });
    render(<LlmSettingsPage />);

    await waitFor(() =>
      expect(screen.getByText(/No providers configured yet/i)).toBeInTheDocument()
    );
  });

  it("keeps Save disabled until a binding is edited, then PUTs configured bindings", async () => {
    primeHappyLoad();
    mockedPut.mockResolvedValue({ bindings: [] });
    render(<LlmSettingsPage />);
    await waitFor(() => expect(screen.getByText("LLM Models")).toBeInTheDocument());

    const save = screen.getByRole("button", { name: /Save changes/i });
    expect(save).toBeDisabled();

    // Configure the OCR scene (a previously empty binding).
    const ocrCard = screen.getByText("Extraction · OCR").closest(".card") as HTMLElement;
    const providerSelect = within(ocrCard).getByLabelText("Provider");
    fireEvent.change(providerSelect, { target: { value: "prov-1" } });
    fireEvent.change(within(ocrCard).getByLabelText("Model"), {
      target: { value: "some-model" },
    });

    expect(save).toBeEnabled();
    fireEvent.click(save);

    await waitFor(() => expect(mockedPut).toHaveBeenCalledTimes(1));
    const sent = mockedPut.mock.calls[0][0].bindings;
    // Only the two configured scenes (advisor.chat from load + edited ocr) persist.
    const scenes = sent.map((b) => b.scene).sort();
    expect(scenes).toEqual(["advisor.chat", "extraction.ocr"]);
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("LLM bindings saved", "success")
    );
  });

  it("edits reasoning, fallbacks and prefer_free then persists them", async () => {
    primeHappyLoad();
    mockedPut.mockResolvedValue({ bindings: [] });
    render(<LlmSettingsPage />);
    await waitFor(() => expect(screen.getByText("LLM Models")).toBeInTheDocument());

    const chatCard = screen.getByText("Advisor · Chat").closest(".card") as HTMLElement;
    fireEvent.change(within(chatCard).getByLabelText("Reasoning depth"), {
      target: { value: "high" },
    });
    fireEvent.change(
      within(chatCard).getByLabelText("Fallback models (comma-separated)"),
      { target: { value: "a, b , " } }
    );
    fireEvent.click(
      within(chatCard).getByLabelText(/Prefer free models for Advisor/i)
    );

    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }));
    await waitFor(() => expect(mockedPut).toHaveBeenCalledTimes(1));

    const chatBinding = mockedPut.mock.calls[0][0].bindings.find(
      (b) => b.scene === "advisor.chat"
    )!;
    expect(chatBinding.reasoning).toBe("high");
    expect(chatBinding.fallback_model_ids).toEqual(["a", "b"]);
    expect(chatBinding.prefer_free).toBe(false); // toggled off from true
  });

  it("Reset reverts edits to the saved bindings", async () => {
    primeHappyLoad();
    render(<LlmSettingsPage />);
    await waitFor(() => expect(screen.getByText("LLM Models")).toBeInTheDocument());

    const chatCard = screen.getByText("Advisor · Chat").closest(".card") as HTMLElement;
    fireEvent.change(within(chatCard).getByLabelText("Reasoning depth"), {
      target: { value: "high" },
    });
    expect(within(chatCard).getByLabelText("Reasoning depth")).toHaveValue("high");

    fireEvent.click(screen.getByRole("button", { name: /Reset/i }));
    expect(within(chatCard).getByLabelText("Reasoning depth")).toHaveValue("low");
    expect(screen.getByRole("button", { name: /Save changes/i })).toBeDisabled();
  });

  it("surfaces a save error and keeps the draft", async () => {
    primeHappyLoad();
    mockedPut.mockRejectedValue(new Error("Save boom"));
    render(<LlmSettingsPage />);
    await waitFor(() => expect(screen.getByText("LLM Models")).toBeInTheDocument());

    const chatCard = screen.getByText("Advisor · Chat").closest(".card") as HTMLElement;
    fireEvent.change(within(chatCard).getByLabelText("Reasoning depth"), {
      target: { value: "high" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Save boom")
    );
    expect(within(chatCard).getByLabelText("Reasoning depth")).toHaveValue("high");
  });

  it("deletes a provider and reloads", async () => {
    primeHappyLoad();
    mockedDelete.mockResolvedValue(undefined);
    render(<LlmSettingsPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Delete provider OpenRouter/i })).toBeInTheDocument());

    // Second load after delete returns no providers.
    mockedProviders.mockResolvedValue({ providers: [] });
    fireEvent.click(
      screen.getByRole("button", { name: /Delete provider OpenRouter/i })
    );

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith("prov-1"));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Provider deleted", "success")
    );
    await waitFor(() =>
      expect(screen.getByText(/No providers configured yet/i)).toBeInTheDocument()
    );
  });

  it("surfaces a delete error", async () => {
    primeHappyLoad();
    mockedDelete.mockRejectedValue(new Error("Delete boom"));
    render(<LlmSettingsPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Delete provider OpenRouter/i })).toBeInTheDocument());

    fireEvent.click(
      screen.getByRole("button", { name: /Delete provider OpenRouter/i })
    );
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Delete boom")
    );
  });

  it("toggles the add-provider form and reloads after creating one", async () => {
    primeHappyLoad();
    mockedCreate.mockResolvedValue(PROVIDER);
    render(<LlmSettingsPage />);
    await waitFor(() => expect(screen.getByText("LLM Models")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Add provider/i }));
    expect(screen.getByLabelText("API key")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Label"), {
      target: { value: "New" },
    });
    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "key" },
    });
    // After opening, the toggle reads "Close", so the only "Add provider"
    // button left is the form's submit.
    fireEvent.click(screen.getByRole("button", { name: /^Add provider$/i }));

    await waitFor(() => expect(mockedCreate).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Provider added", "success")
    );
    // Form closes after creation.
    await waitFor(() =>
      expect(screen.queryByLabelText("API key")).not.toBeInTheDocument()
    );
  });

  it("closes the add-provider form via the toggle", async () => {
    primeHappyLoad();
    render(<LlmSettingsPage />);
    await waitFor(() => expect(screen.getByText("LLM Models")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Add provider/i }));
    expect(screen.getByLabelText("API key")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Close/i }));
    expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
  });

  it("closes the add-provider form via its Cancel button", async () => {
    primeHappyLoad();
    render(<LlmSettingsPage />);
    await waitFor(() => expect(screen.getByText("LLM Models")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Add provider/i }));
    fireEvent.click(screen.getByRole("button", { name: /Cancel/i }));
    expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
  });
});
