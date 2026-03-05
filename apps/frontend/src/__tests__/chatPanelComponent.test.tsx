import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import ChatPanel from "@/components/ChatPanel"
import { apiDelete, apiFetch, apiStream } from "@/lib/api"
import { fetchAiModels } from "@/lib/aiModels"

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
  apiStream: vi.fn(),
  apiDelete: vi.fn(),
}))

vi.mock("@/lib/aiModels", () => ({
  fetchAiModels: vi.fn(),
}))

function streamingResponse(text: string): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text))
      controller.close()
    },
  })
  return new Response(stream)
}

describe("ChatPanel", () => {
  const mockedApiFetch = vi.mocked(apiFetch)
  const mockedApiStream = vi.mocked(apiStream)
  const mockedApiDelete = vi.mocked(apiDelete)
  const mockedFetchAiModels = vi.mocked(fetchAiModels)

  beforeEach(() => {
    mockedApiFetch.mockReset()
    mockedApiStream.mockReset()
    mockedApiDelete.mockReset()
    mockedFetchAiModels.mockReset()

    const storage = new Map<string, string>([["ai_chat_session_id", "sess-1"]])
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value)
      },
      removeItem: (key: string) => {
        storage.delete(key)
      },
    })

    mockedFetchAiModels.mockResolvedValue({
      models: [{ 
        id: "model-1", 
        name: "Model 1", 
        is_free: true,
        input_modalities: ["text"],
        pricing: { prompt: "0", completion: "0" }
      }],
      default_model: "model-1",
      fallback_models: [],
    })

    mockedApiFetch.mockImplementation((path: string) => {
      if (path.includes("/api/chat/suggestions")) {
        return Promise.resolve({ suggestions: ["How is cash flow?"] })
      }
      if (path.includes("/api/chat/history")) {
        return Promise.resolve({ sessions: [{ id: "sess-1", messages: [] }] })
      }
      return Promise.resolve({})
    })

    mockedApiStream.mockResolvedValue({ response: streamingResponse("Assistant answer") as Response, sessionId: "sess-2" })
    mockedApiDelete.mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("AC16.20.5 loads suggestions/history and streams reply", async () => {
    render(<ChatPanel variant="page" />)

    await waitFor(() => expect(screen.getByText("How is cash flow?")).toBeInTheDocument())
    fireEvent.click(screen.getByText("How is cash flow?"))

    await waitFor(() => expect(mockedApiStream).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText("Assistant answer")).toBeInTheDocument())
  })

  it("AC16.20.5 clears existing session", async () => {
    render(<ChatPanel variant="page" />)
    // Wait for history to load (sessionId gets set from loadHistory)
    await waitFor(() => expect(screen.queryByText(/Loading chat history/i)).not.toBeInTheDocument())
    await waitFor(() => expect(screen.getByRole("button", { name: "Clear" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Clear" }))
  })

  it("handles model selection", async () => {
    render(<ChatPanel variant="page" />)
    const select = await screen.findByLabelText(/ai model/i) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "model-1" } })
    expect(select.value).toBe("model-1")
    expect(localStorage.getItem("ai_chat_model_v1")).toBe("model-1")
  })

  it("sends message via enter key", async () => {
    render(<ChatPanel variant="page" />)
    const textarea = screen.getByPlaceholderText(/Ask about spending trends/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Hello AI" } })
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false })
    await waitFor(() => expect(mockedApiStream).toHaveBeenCalled())
  })

  it("sends message via button", async () => {
    render(<ChatPanel variant="page" />)
    const textarea = screen.getByPlaceholderText(/Ask about spending trends/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Hello AI 2" } })
    fireEvent.click(screen.getByRole("button", { name: "Send" }))
    await waitFor(() => expect(mockedApiStream).toHaveBeenCalled())
  })

  it("handles initialPrompt", async () => {
    render(<ChatPanel variant="page" initialPrompt="Analyze my data" />)
    await waitFor(() => expect(mockedApiStream).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({
      body: expect.stringContaining("Analyze my data")
    })))
  })

  it("handles missing stream reader", async () => {
    mockedApiStream.mockResolvedValue({ response: { body: null } as any, sessionId: "sess-3" })
    render(<ChatPanel variant="page" />)
    await waitFor(() => expect(screen.queryByText(/Loading chat history/i)).not.toBeInTheDocument())
    const textarea = screen.getByPlaceholderText(/Ask about spending trends/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Hello" } })
    fireEvent.click(screen.getByRole("button", { name: "Send" }))
    await waitFor(() => expect(screen.getByText("No response stream available.")).toBeInTheDocument())
  })

  it("handles send message error", async () => {
    mockedApiStream.mockRejectedValue(new Error("Network Fail"))
    render(<ChatPanel variant="page" />)
    await waitFor(() => expect(screen.queryByText(/Loading chat history/i)).not.toBeInTheDocument())
    const textarea = screen.getByPlaceholderText(/Ask about spending trends/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Hello" } })
    fireEvent.click(screen.getByRole("button", { name: "Send" }))
    await waitFor(() => expect(screen.getAllByText("Network Fail").length).toBeGreaterThan(0))
  })

  it("handles suggestions fetch failure", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.includes("/api/chat/suggestions")) {
        return Promise.reject(new Error("Suggestions fail"))
      }
      if (path.includes("/api/chat/history")) {
        return Promise.resolve({ sessions: [{ id: "sess-1", messages: [] }] })
      }
      return Promise.resolve({})
    })
    render(<ChatPanel variant="page" />)
    await waitFor(() => expect(screen.queryByText(/Loading chat history/i)).not.toBeInTheDocument())
    expect(screen.queryByText("How is cash flow?")).not.toBeInTheDocument()
  })

  it("handles history fetch failure", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.includes("/api/chat/suggestions")) {
        return Promise.resolve({ suggestions: ["Tip 1"] })
      }
      if (path.includes("/api/chat/history")) {
        return Promise.reject(new Error("History fail"))
      }
      return Promise.resolve({})
    })
    render(<ChatPanel variant="page" />)
    await waitFor(() => expect(screen.queryByText(/Loading chat history/i)).not.toBeInTheDocument())
    expect(localStorage.getItem("ai_chat_session_id")).toBeNull()
  })

  it("handles AI model fetch failure", async () => {
    mockedFetchAiModels.mockRejectedValue(new Error("Models fail"))
    render(<ChatPanel variant="page" />)
    await waitFor(() => expect(screen.queryByText(/Loading chat history/i)).not.toBeInTheDocument())
    const select = screen.queryByLabelText(/ai model/i)
    if (select) {
      expect((select as HTMLSelectElement).options.length).toBeLessThanOrEqual(1)
    }
  })

  it("falls back to first model when default_model not in list", async () => {
    mockedFetchAiModels.mockResolvedValue({
      models: [{
        id: "model-alt",
        name: "Alt Model",
        is_free: true,
        input_modalities: ["text"],
        pricing: { prompt: "0", completion: "0" }
      }],
      default_model: "nonexistent-model",
      fallback_models: [],
    })
    render(<ChatPanel variant="page" />)
    const select = await screen.findByLabelText(/ai model/i) as HTMLSelectElement
    await waitFor(() => expect(select.value).toBe("model-alt"))
  })
})
