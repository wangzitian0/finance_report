import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LlmSettingsPage from "@/components/settings/LlmSettingsPanel";
import { apiOperation } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiOperation: vi.fn(),
}));

const showToast = vi.fn();
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ showToast }),
}));

const mockedApiOperation = vi.mocked(apiOperation);

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
  mockedApiOperation.mockImplementation(async (op: any) => {
    if (op === "list_providers_llm_providers_get") {
      return { providers: [PROVIDER] } as any;
    }
    if (op === "get_catalog_llm_catalog_get") {
      return { models: [MODEL] } as any;
    }
    if (op === "get_scenes_llm_scenes_get") {
      return {
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
      } as any;
    }
    if (op === "put_scenes_llm_scenes_put") {
      return { bindings: [] } as any;
    }
    if (op === "delete_provider_llm_providers__provider_id__delete") {
      return undefined as any;
    }
    if (op === "create_provider_llm_providers_post") {
      return PROVIDER as any;
    }
    return {} as any;
  });
}

beforeEach(() => {
  showToast.mockReset();
  mockedApiOperation.mockReset();
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
    mockedApiOperation.mockRejectedValue(new Error("Load failed"));
    render(<LlmSettingsPage />);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Load failed")
    );
  });

  it("renders an empty-providers hint when none are configured", async () => {
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "list_providers_llm_providers_get") return { providers: [] } as any;
      if (op === "get_scenes_llm_scenes_get") return { bindings: [] } as any;
      if (op === "get_catalog_llm_catalog_get") return { models: [] } as any;
      return {} as any;
    });
    render(<LlmSettingsPage />);

    await waitFor(() =>
      expect(screen.getByText(/No providers configured yet/i)).toBeInTheDocument()
    );
  });

  it("keeps Save disabled until a binding is edited, then PUTs configured bindings", async () => {
    primeHappyLoad();
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

    await waitFor(() => {
      const putCalls = mockedApiOperation.mock.calls.filter(([op]) => op === "put_scenes_llm_scenes_put");
      expect(putCalls).toHaveLength(1);
    });
    const putCalls = mockedApiOperation.mock.calls.filter(([op]) => op === "put_scenes_llm_scenes_put");
    const sent = (putCalls[0][1] as any).body.bindings;
    // Only the two configured scenes (advisor.chat from load + edited ocr) persist.
    const scenes = sent.map((b: any) => b.scene).sort();
    expect(scenes).toEqual(["advisor.chat", "extraction.ocr"]);
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("LLM bindings saved", "success")
    );
  });

  it("edits reasoning, fallbacks and prefer_free then persists them", async () => {
    primeHappyLoad();
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
    await waitFor(() => {
      const putCalls = mockedApiOperation.mock.calls.filter(([op]) => op === "put_scenes_llm_scenes_put");
      expect(putCalls).toHaveLength(1);
    });

    const putCalls = mockedApiOperation.mock.calls.filter(([op]) => op === "put_scenes_llm_scenes_put");
    const chatBinding = (putCalls[0][1] as any).body.bindings.find(
      (b: any) => b.scene === "advisor.chat"
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
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "put_scenes_llm_scenes_put") throw new Error("Save boom");
      if (op === "list_providers_llm_providers_get") return { providers: [PROVIDER] } as any;
      if (op === "get_catalog_llm_catalog_get") return { models: [MODEL] } as any;
      if (op === "get_scenes_llm_scenes_get") {
        return {
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
        } as any;
      }
      return {} as any;
    });
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
    let providers = [PROVIDER];
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "list_providers_llm_providers_get") return { providers } as any;
      if (op === "get_catalog_llm_catalog_get") return { models: [MODEL] } as any;
      if (op === "get_scenes_llm_scenes_get") return { bindings: [] } as any;
      if (op === "delete_provider_llm_providers__provider_id__delete") {
        providers = [];
        return undefined as any;
      }
      return {} as any;
    });
    render(<LlmSettingsPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Delete provider OpenRouter/i })).toBeInTheDocument());

    fireEvent.click(
      screen.getByRole("button", { name: /Delete provider OpenRouter/i })
    );
    // #1609: destructive delete now goes through a confirmation dialog.
    fireEvent.click(
      await screen.findByRole("button", { name: "Delete provider" })
    );

    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith(
        "delete_provider_llm_providers__provider_id__delete",
        { path: { provider_id: "prov-1" } },
      )
    );
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Provider deleted", "success")
    );
    await waitFor(() =>
      expect(screen.getByText(/No providers configured yet/i)).toBeInTheDocument()
    );
  });

  it("surfaces a delete error", async () => {
    primeHappyLoad();
    mockedApiOperation.mockImplementation(async (op: any) => {
      if (op === "delete_provider_llm_providers__provider_id__delete") throw new Error("Delete boom");
      if (op === "list_providers_llm_providers_get") return { providers: [PROVIDER] } as any;
      if (op === "get_catalog_llm_catalog_get") return { models: [MODEL] } as any;
      if (op === "get_scenes_llm_scenes_get") return { bindings: [] } as any;
      return {} as any;
    });
    render(<LlmSettingsPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Delete provider OpenRouter/i })).toBeInTheDocument());

    fireEvent.click(
      screen.getByRole("button", { name: /Delete provider OpenRouter/i })
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Delete provider" })
    );
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Delete boom")
    );
  });

  it("#1609 does not delete until the confirmation is accepted", async () => {
    primeHappyLoad();
    render(<LlmSettingsPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Delete provider OpenRouter/i })).toBeInTheDocument());

    fireEvent.click(
      screen.getByRole("button", { name: /Delete provider OpenRouter/i })
    );
    // The confirm dialog is shown and nothing has been deleted yet.
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(mockedApiOperation).not.toHaveBeenCalledWith(
      "delete_provider_llm_providers__provider_id__delete",
      expect.anything(),
    );

    // Cancelling closes the dialog without deleting.
    fireEvent.click(screen.getByRole("button", { name: /Cancel/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(mockedApiOperation).not.toHaveBeenCalledWith(
      "delete_provider_llm_providers__provider_id__delete",
      expect.anything(),
    );
  });

  it("toggles the add-provider form and reloads after creating one", async () => {
    primeHappyLoad();
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

    await waitFor(() =>
      expect(mockedApiOperation).toHaveBeenCalledWith(
        "create_provider_llm_providers_post",
        expect.objectContaining({
          body: expect.objectContaining({ label: "New", api_key: "key" }),
        }),
      )
    );
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
