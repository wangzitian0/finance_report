import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FirstRunModal } from "@/components/llm/FirstRunModal";
import { createLlmProvider } from "@/lib/api";
import { useLlmConfigStatus } from "@/hooks/useLlmConfigStatus";

vi.mock("@/lib/api", () => ({
  createLlmProvider: vi.fn(),
}));

vi.mock("@/hooks/useLlmConfigStatus", () => ({
  useLlmConfigStatus: vi.fn(),
}));

const mockedCreate = vi.mocked(createLlmProvider);
const mockedHook = vi.mocked(useLlmConfigStatus);
const refresh = vi.fn();

function setStatus(configured: boolean | null) {
  mockedHook.mockReturnValue({ configured, loading: false, refresh });
}

beforeEach(() => {
  mockedCreate.mockReset();
  refresh.mockReset();
});

describe("FirstRunModal (EPIC-023 PR4)", () => {
  it("renders nothing while the status is unknown", () => {
    setStatus(null);
    const { container } = render(<FirstRunModal />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when already configured", () => {
    setStatus(true);
    const { container } = render(<FirstRunModal />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the provider form when unconfigured, pre-filling the OpenRouter base", () => {
    setStatus(false);
    render(<FirstRunModal />);

    expect(screen.getByText("Set up your AI provider")).toBeInTheDocument();
    expect(screen.getByLabelText("API base URL")).toHaveValue(
      "https://openrouter.ai/api/v1"
    );
    // Default protocol is the OpenRouter-compatible family.
    expect(screen.getByLabelText("Protocol family")).toHaveValue(
      "openrouter-compatible"
    );
  });

  it("creates the provider and refreshes status on submit", async () => {
    setStatus(false);
    mockedCreate.mockResolvedValue({
      id: "p1",
      label: "My key",
      protocol: "openrouter-compatible",
      api_base: "https://openrouter.ai/api/v1",
      has_api_key: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });

    render(<FirstRunModal />);

    fireEvent.change(screen.getByLabelText("Label"), {
      target: { value: "My key" },
    });
    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "sk-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save provider/i }));

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith({
        label: "My key",
        protocol: "openrouter-compatible",
        api_key: "sk-secret",
        api_base: "https://openrouter.ai/api/v1",
      })
    );
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  });

  it("can be dismissed via Cancel without configuring", () => {
    setStatus(false);
    render(<FirstRunModal />);

    fireEvent.click(screen.getByRole("button", { name: /Cancel/i }));
    expect(screen.queryByText("Set up your AI provider")).not.toBeInTheDocument();
    expect(mockedCreate).not.toHaveBeenCalled();
  });

  it("surfaces an error when create fails and keeps the form open", async () => {
    setStatus(false);
    mockedCreate.mockRejectedValue(new Error("Bad key"));

    render(<FirstRunModal />);
    fireEvent.change(screen.getByLabelText("Label"), {
      target: { value: "My key" },
    });
    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "sk" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save provider/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Bad key")
    );
    expect(refresh).not.toHaveBeenCalled();
  });

  it("submits api_base as null when cleared", async () => {
    setStatus(false);
    mockedCreate.mockResolvedValue({
      id: "p1",
      label: "L",
      protocol: "openai-compatible",
      api_base: null,
      has_api_key: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });

    render(<FirstRunModal />);
    fireEvent.change(screen.getByLabelText("API base URL"), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText("Protocol family"), {
      target: { value: "openai-compatible" },
    });
    fireEvent.change(screen.getByLabelText("Label"), {
      target: { value: "L" },
    });
    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "k" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save provider/i }));

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith({
        label: "L",
        protocol: "openai-compatible",
        api_key: "k",
        api_base: null,
      })
    );
  });
});
