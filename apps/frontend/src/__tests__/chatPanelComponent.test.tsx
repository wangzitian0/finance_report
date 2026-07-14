import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
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

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => <a href={href} {...props}>{children}</a>,
}))

function streamingResponse(text: string, headers?: HeadersInit): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text))
      controller.close()
    },
  })
  return new Response(stream, { headers })
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
        return Promise.resolve({
          suggestions: ["How is cash flow?"],
          structured_suggestions: [
            {
              basis: "Report package is blocked by one review-required item.",
              confidence_tier: "blocked",
              source_refs: ["workflow.status", "report_package.readiness"],
              limitation: "Review the blocker before relying on this report.",
              next_action_href: "/reports/package",
            },
          ],
        })
      }
      if (path.includes("/api/chat/history")) {
        return Promise.resolve({ sessions: [{ id: "sess-1", title: "Cash flow review", message_count: 0, messages: [] }] })
      }
      return Promise.resolve({})
    })

    mockedApiStream.mockResolvedValue({ response: streamingResponse("Assistant answer") as Response, sessionId: "sess-2" })
    mockedApiDelete.mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // AC-advisor.fe-chat.4
  it("AC16.20.5 loads suggestions/history and streams reply", async () => {
    render(<ChatPanel variant="page" />)

    await waitFor(() => expect(screen.getByText("How is cash flow?")).toBeInTheDocument())
    fireEvent.click(screen.getByText("How is cash flow?"))

    await waitFor(() => expect(mockedApiStream).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText("Assistant answer")).toBeInTheDocument())
  })

  it("AC21.3.3 test_AC21_3_3_chat_panel_renders_contextual_advisor_brief", async () => {
    render(<ChatPanel variant="page" />)

    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/chat/suggestions?language=en&include_structured=true"),
      ),
    )
    const brief = await screen.findByLabelText("Advisor Brief")
    expect(within(brief).getByText("Report package is blocked by one review-required item.")).toBeInTheDocument()
    expect(within(brief).getByText("Review the blocker before relying on this report.")).toBeInTheDocument()
    expect(within(brief).getByRole("link", { name: "Open next action" })).toHaveAttribute("href", "/reports/package")
    expect(within(brief).getByRole("link", { name: "Ask about this" })).toHaveAttribute(
      "href",
      expect.stringContaining("/chat?prompt="),
    )

    fireEvent.click(screen.getByText("How is cash flow?"))
    await waitFor(() => expect(mockedApiStream).toHaveBeenCalled())
  })

  // AC-advisor.fe-ia-chat.1
  it("AC22.14.2 AC22.14.3 renders grounded answer citations and pending action chips", async () => {
    mockedApiStream.mockResolvedValue({
      response: streamingResponse("Your net worth is SGD 900.00", {
        "X-Advisor-Metadata": JSON.stringify({
          grounded: true,
          citations: [
            {
              label: "Balance Sheet",
              source_ref: "balance_sheet.total_equity",
              confidence_tier: "TRUSTED",
              href: "/reports/balance-sheet",
            },
          ],
          actions: [
            {
              kind: "reconciliation_review",
              label: "Review 2",
              href: "/reconciliation/review-queue",
              count: 2,
            },
          ],
        }),
      }) as Response,
      sessionId: "sess-2",
    })

    render(<ChatPanel variant="page" />)

    await waitFor(() => expect(screen.queryByText(/Loading chat history/i)).not.toBeInTheDocument())
    fireEvent.click(screen.getByText("How is cash flow?"))

    expect(await screen.findByText("Your net worth is SGD 900.00")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Balance Sheet TRUSTED" })).toHaveAttribute(
      "href",
      "/reports/balance-sheet",
    )
    expect(screen.getByRole("link", { name: "Review 2" })).toHaveAttribute(
      "href",
      "/reconciliation/review-queue",
    )
  })

  it("AC16.20.5 starts a new conversation from the active session", async () => {
    render(<ChatPanel variant="page" />)
    // Wait for history to load (sessionId gets set from loadHistory)
    await waitFor(() => expect(screen.queryByText(/Loading chat history/i)).not.toBeInTheDocument())
    await waitFor(() => expect(screen.getByRole("button", { name: "New" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "New" }))
    await waitFor(() => expect(mockedApiDelete).toHaveBeenCalledWith("/api/chat/session/sess-1"))
    expect(localStorage.getItem("ai_chat_session_id")).toBeNull()
  })

  it("AC8.13.92 keeps widget close and disclaimer rendering covered", async () => {
    const onClose = vi.fn()
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.includes("/api/chat/suggestions")) {
        return Promise.resolve({ suggestions: [] })
      }
      if (path.includes("/api/chat/history")) {
        return Promise.resolve({
          sessions: [
            {
              id: "sess-1",
              title: "Risk review",
              message_count: 1,
              messages: [
                {
                  id: "m1",
                  role: "assistant",
                  content: "Portfolio risk is concentrated. The above analysis is for reference only.",
                },
              ],
            },
          ],
        })
      }
      return Promise.resolve({})
    })

    render(<ChatPanel variant="widget" onClose={onClose} />)

    expect(await screen.findByText("Portfolio risk is concentrated.")).toBeInTheDocument()
    expect(screen.getByText("The above analysis is for reference only.")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Close" }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("AC19.8.6 shows chat sessions inside the AI page without workflow ownership", async () => {
    render(<ChatPanel variant="page" />)

    fireEvent.click(await screen.findByRole("button", { name: "Sessions" }))
    expect(await screen.findByRole("dialog", { name: "AI sessions" })).toBeInTheDocument()
    expect(screen.getByText("Cash flow review")).toBeInTheDocument()
    fireEvent.click(screen.getByText("Cash flow review"))
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/api/chat/history?session_id=sess-1"))
  })

  it("AC19.8.6 renders an empty session drawer when no chat history exists", async () => {
    const storage = new Map<string, string>()
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value)
      },
      removeItem: (key: string) => {
        storage.delete(key)
      },
    })
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.includes("/api/chat/suggestions")) {
        return Promise.resolve({ suggestions: [] })
      }
      if (path.includes("/api/chat/history")) {
        return Promise.resolve({ sessions: [] })
      }
      return Promise.resolve({})
    })

    render(<ChatPanel variant="page" />)

    await waitFor(() => expect(screen.queryByText(/Loading chat history/i)).not.toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Sessions" }))
    expect(await screen.findByText("No saved conversations yet.")).toBeInTheDocument()
  })

  it("AC19.8.6 closes the chat session drawer without changing the active conversation", async () => {
    render(<ChatPanel variant="page" />)

    fireEvent.click(await screen.findByRole("button", { name: "Sessions" }))
    const dialog = await screen.findByRole("dialog", { name: "AI sessions" })
    fireEvent.click(screen.getByRole("button", { name: "Close panel" }))

    await waitFor(() => expect(dialog).not.toBeInTheDocument())
    expect(localStorage.getItem("ai_chat_session_id")).toBe("sess-1")
  })

  it("AC16.20.5 handles model selection", async () => {
    mockedFetchAiModels.mockResolvedValue({
      models: [
        {
          id: "model-1",
          name: "Model 1",
          is_free: true,
          input_modalities: ["text"],
          pricing: { prompt: "0", completion: "0" },
        },
        {
          id: "model-2",
          name: "Model 2",
          is_free: false,
          input_modalities: ["text"],
          pricing: { prompt: "0.1", completion: "0.2" },
        },
      ],
      default_model: "model-1",
      fallback_models: [],
    })
    render(<ChatPanel variant="page" />)
    const select = (await screen.findByLabelText(/ai model/i)) as HTMLSelectElement

    await waitFor(() => expect(select.value).toBe("model-1"))
    fireEvent.change(select, { target: { value: "model-2" } })

    expect(select.value).toBe("model-2")
    expect(localStorage.getItem("ai_chat_model_v1")).toBe("model-2")
  })

  it("AC16.20.5 sends message via enter key", async () => {
    render(<ChatPanel variant="page" />)
    const textarea = screen.getByPlaceholderText(/Ask about spending trends/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Hello AI" } })
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false })
    await waitFor(() => expect(mockedApiStream).toHaveBeenCalled())
  })

  it("AC16.20.5 sends message via button", async () => {
    render(<ChatPanel variant="page" />)
    const textarea = screen.getByPlaceholderText(/Ask about spending trends/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Hello AI 2" } })
    fireEvent.click(screen.getByRole("button", { name: "Send" }))
    await waitFor(() => expect(mockedApiStream).toHaveBeenCalled())
  })

  it("AC16.20.5 handles initialPrompt", async () => {
    render(<ChatPanel variant="page" initialPrompt="Analyze my data" />)
    await waitFor(() => expect(mockedApiStream).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({
      body: expect.stringContaining("Analyze my data")
    })))
  })

  // AC-advisor.fe-chat.5
  it("AC16.20.7 handles missing stream reader", async () => {
    mockedApiStream.mockResolvedValue({ response: { body: null } as any, sessionId: "sess-3" })
    render(<ChatPanel variant="page" />)
    await waitFor(() => expect(screen.queryByText(/Loading chat history/i)).not.toBeInTheDocument())
    const textarea = screen.getByPlaceholderText(/Ask about spending trends/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Hello" } })
    fireEvent.click(screen.getByRole("button", { name: "Send" }))
    await waitFor(() => expect(screen.getByText("No response stream available.")).toBeInTheDocument())
  })

  it("AC16.20.7 handles send message error", async () => {
    mockedApiStream.mockRejectedValue(new Error("Network Fail"))
    render(<ChatPanel variant="page" />)
    await waitFor(() => expect(screen.queryByText(/Loading chat history/i)).not.toBeInTheDocument())
    const textarea = screen.getByPlaceholderText(/Ask about spending trends/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Hello" } })
    fireEvent.click(screen.getByRole("button", { name: "Send" }))
    await waitFor(() => expect(screen.getAllByText("Network Fail").length).toBeGreaterThan(0))
  })

  it("AC16.20.7 handles suggestions fetch failure", async () => {
    mockedApiFetch.mockImplementation((path: string) => {
      if (path.includes("/api/chat/suggestions")) {
        return Promise.reject(new Error("Suggestions fail"))
      }
      if (path.includes("/api/chat/history")) {
        return Promise.resolve({ sessions: [{ id: "sess-1", title: "Tip session", message_count: 0, messages: [] }] })
      }
      return Promise.resolve({})
    })
    render(<ChatPanel variant="page" />)
    await waitFor(() => expect(screen.queryByText(/Loading chat history/i)).not.toBeInTheDocument())
    expect(screen.queryByText("How is cash flow?")).not.toBeInTheDocument()
  })

  it("AC16.20.7 handles history fetch failure", async () => {
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

  it("AC16.20.7 handles history fetch failure without a stored chat session", async () => {
    const storage = new Map<string, string>()
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value)
      },
      removeItem: (key: string) => {
        storage.delete(key)
      },
    })
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
    fireEvent.click(screen.getByRole("button", { name: "Sessions" }))
    expect(await screen.findByText("No saved conversations yet.")).toBeInTheDocument()
  })

  it("AC16.20.7 handles AI model fetch failure", async () => {
    mockedFetchAiModels.mockRejectedValue(new Error("Models fail"))
    render(<ChatPanel variant="page" />)
    await waitFor(() => expect(screen.queryByText(/Loading chat history/i)).not.toBeInTheDocument())
    const select = screen.queryByLabelText(/ai model/i)
    if (select) {
      expect((select as HTMLSelectElement).options.length).toBeLessThanOrEqual(1)
    }
  })

  it("AC16.20.7 falls back to first model when default_model not in list", async () => {
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
