import { render as R, screen as S } from "@testing-library/react";
import { beforeEach, describe, expect as E, it, vi } from "vitest";
import { AiSettingsPanel, changedChoices } from "@/components/settings/SettingsPanels";
import { apiOperation } from "@/lib/api";
import * as X from "./helpers/shellTestFixtures";

const showToast = vi.fn();
vi.mock("next/link", async () => (await import("./helpers/shellTestFixtures")).linkMock);
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast }) }));
const api = vi.mocked(apiOperation), D = X.AI_SETTINGS_DEFAULT;

describe("AiSettingsPanel", () => {
  beforeEach(() => { showToast.mockReset(); api.mockReset(); X.mockAiSettingsRoutes(api); });

  it("links, saves edits, resets", async () => {
    X.mockAiSettingsRoutes(api, D, { ...D, enable_ai_classification: true, auto_accept_ai_suggestions_active: true });
    R(<AiSettingsPanel />); await X.runAiSettingsSaveFlow(api, showToast);
  });

  it("toggles & PATCH/GET errors & changedChoices", async () => {
    await X.runAiToggleAndErrorFlows(api, () => R(<AiSettingsPanel />));
    X.checkChangedChoicesFn(changedChoices);
  });

  it.each(X.AI_NOTE_CASES)("note %#", async (c, ch, act, shown) => {
    X.mockAiSettingsRoutes(api, { enable_ai_reconciliation: false, enable_ai_classification: c, auto_accept_ai_suggestions: ch, auto_accept_ai_suggestions_active: act });
    R(<AiSettingsPanel />); await S.findByText("AI Settings");
    const note = S.queryByRole("note");
    if (shown) E(note).toHaveTextContent("turned the automatic acceptance off for all accounts"); else E(note).toBeNull();
  });
});
// AC-llm.fe-ia-ai-settings.1 AC-reconciliation.fe-ia-reconciliation.1
