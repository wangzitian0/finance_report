import { render as R, screen as S, waitFor as W } from "@testing-library/react";
import { beforeEach, describe, expect as E, it, vi } from "vitest";
import ChatPanel from "@/components/chat/ChatPanel";
import { apiOperation, apiOperationStream } from "@/lib/api";
import * as X from "./helpers/shellTestFixtures";

vi.mock("@/lib/api", () => ({ apiOperation: vi.fn(), apiOperationStream: vi.fn() }));
vi.mock("next/link", async () => (await import("./helpers/shellTestFixtures")).linkMock);
const api = vi.mocked(apiOperation), stream = vi.mocked(apiOperationStream);
const mockChat = (s: unknown = X.CHAT_SUGGESTIONS, h: unknown = X.CHAT_EMPTY_HISTORY) => X.mockApiMap(api, { [X.OPS.SUG]: s, [X.OPS.CHAT_HIST]: h }, {});

describe("ChatPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear(); localStorage.setItem("ai_chat_session_id", "sess-1");
    mockChat();
    stream.mockResolvedValue({ response: X.makeStreamRes("Assistant answer"), sessionId: "sess-2" });
  });

  it("AdvisorBrief, suggestion, New", async () => {
    R(<ChatPanel />); await X.checkChatBrief();
    X.clkTxt("How is cash flow?"); await S.findByText("Assistant answer");
    X.clkBtn("New"); await X.waitOp(api, X.OPS.CHAT_DEL, { path: { session_id: "sess-2" } });
    E(localStorage.getItem("ai_chat_session_id")).toBeNull();
  });

  it("citations, chips, bubbles, tables", async () => {
    stream.mockResolvedValue({ response: X.makeStreamRes("Your net worth is SGD 900.00", X.CHAT_GROUNDED_HEADERS), sessionId: "sess-2" });
    const v1 = R(<ChatPanel />); await W(() => X.noTxt(/Loading chat history/i));
    X.clkTxt("How is cash flow?"); await S.findByText("Your net worth is SGD 900.00");
    X.chkLnk("Balance Sheet TRUSTED", "/reports?tab=balance-sheet"); X.chkLnk("Review 2", "/reconciliation?tab=review-queue"); v1.unmount();

    mockChat({ suggestions: [] }, X.CHAT_TABLE_HISTORY);
    const { container } = R(<ChatPanel initialPrompt="Analyze this account" />);
    E(await S.findByTestId("chat-bubble-user")).toHaveClass("justify-end");
    E(S.getByTestId("chat-bubble-assistant")).toHaveClass("justify-start");
    X.checkChatTable(container);
  });

  it("sessions, send, auto-send without model selector", async () => {
    const v1 = R(<ChatPanel />); await X.runChatSessionsFlow(api, stream);
    E(S.queryByLabelText(/ai model/i)).toBeNull(); v1.unmount();
    R(<ChatPanel initialPrompt="Analyze my data" />);
    await W(() => E(stream).toHaveBeenCalledWith(X.OPS.CHAT_POST, E.objectContaining({ body: { message: "Analyze my data", session_id: "sess-1" } })));
  });

  it("empty sessions, fallback, errors", async () => {
    await X.runChatErrorStates(() => R(<ChatPanel />), stream);
    localStorage.clear();
    mockChat(() => { throw new Error("S"); }, () => { throw new Error("H"); });
    R(<ChatPanel />); await W(() => X.noTxt(/Loading chat history/i)); X.clkBtn("Sessions"); await S.findByText("No saved conversations yet.");
  });
});
