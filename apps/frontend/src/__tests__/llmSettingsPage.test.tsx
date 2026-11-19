import { fireEvent as F, render as R, screen as S } from "@testing-library/react";
import { beforeEach, describe, it, vi } from "vitest";
import SettingsPage from "@/app/(main)/settings/page";
import { LlmSettingsPanel } from "@/components/settings/SettingsPanels";
import { apiOperation } from "@/lib/api";
import * as X from "./helpers/shellTestFixtures";

const showToast = vi.fn();
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams("tab=llm"), useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast }) }));
const api = vi.mocked(apiOperation);

describe("LlmSettingsPanel", () => {
  beforeEach(() => { showToast.mockReset(); api.mockReset(); X.mockLlmRoutes(api); });

  it("loads, empty/error, links Portfolio", async () => {
    const v1 = R(<LlmSettingsPanel />); await X.checkLlmLoaded(); v1.unmount();
    X.mockLlmRoutes(api, X.LLM_EMPTY_ROUTES); const v2 = R(<LlmSettingsPanel />); await S.findByText(/No providers configured yet/i); v2.unmount();
    api.mockRejectedValueOnce(new Error("Load failed")); const v3 = R(<LlmSettingsPanel />); await X.findAlert("Load failed"); v3.unmount();
    X.mockLlmRoutes(api); R(<SettingsPage />); X.chkLnk("Portfolio Holdings", "/portfolio");
  });

  it("edits, saves, resets, errors", async () => {
    const v1 = R(<LlmSettingsPanel />); await X.runLlmEditAndSave(api, showToast); v1.unmount();
    X.mockLlmRoutes(api, { [X.OPS.LLM_SCENES_PUT]: () => { throw new Error("Save boom"); } });
    R(<LlmSettingsPanel />); await S.findByText("LLM Models");
    F.change(X.cardInput("Advisor · Chat", "Reasoning depth"), { target: { value: "high" } }); X.clkBtn(/Save changes/i);
    await X.findAlert("Save boom");
  });

  it("adds, deletes, toggles form", async () => {
    let p = [X.LLM_PROVIDER];
    X.mockLlmRoutes(api, { [X.OPS.LLM_PROV_LIST]: () => ({ providers: p }), [X.OPS.LLM_PROV_DEL]: () => { p = []; } });
    const v1 = R(<LlmSettingsPanel />); await X.runLlmDeleteSuccess(api, showToast); v1.unmount();
    p = [X.LLM_PROVIDER]; await X.runLlmAddAndDeleteErr(api, showToast, () => R(<LlmSettingsPanel />));
  });
});
