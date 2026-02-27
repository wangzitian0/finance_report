import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

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
      models: [{ id: "model-1", name: "Model 1", is_free: true }],
      default_model: "model-1",
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
    mockedApiDelete.mockResolvedValue({ ok: true })
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

    await waitFor(() => expect(screen.getByRole("button", { name: "Clear" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Clear" }))

    await waitFor(() => expect(mockedApiDelete).toHaveBeenCalledWith("/api/chat/session/sess-1"))
  })
})
