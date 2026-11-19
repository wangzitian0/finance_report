import { act, render as R, renderHook as RH, screen as S, waitFor as W } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect as E, it, vi } from "vitest";
import { InstallAppPromptView } from "@/components/AppShell";
import { PWA_INSTALL_DISMISS_COOLDOWN_MS, PWA_INSTALL_DISMISSED_AT_KEY, isIosLikeNavigator, isStandaloneDisplay, usePwaInstall } from "@/hooks/usePwaInstall";
import * as X from "./helpers/shellTestFixtures";

describe("PWA install", () => {
  beforeEach(() => X.resetPwaDefaults());

  it("AC22.20.1 manifest & AppShell", () =>
    X.checkPwaManifestAndShell(readFileSync(resolve(process.cwd(), "public/site.webmanifest"), "utf8"), readFileSync(resolve(process.cwd(), "src/components/AppShell.tsx"), "utf8")));

  it("AC22.20.2 native accept, dismiss, cooldown, expiry", () =>
    X.runPwaNativeChecks(usePwaInstall, act, RH, PWA_INSTALL_DISMISSED_AT_KEY, PWA_INSTALL_DISMISS_COOLDOWN_MS));

  it("AC22.20.4 iOS, standalone, events", async () => {
    const dm = X.mockPwaDisplayMode(false);
    X.setPwaNavigator({ maxTouchPoints: 1, platform: "iPhone", userAgent: "iPhone" }); E([isIosLikeNavigator(), isStandaloneDisplay()]).toEqual([true, false]);
    X.setPwaNavigator({ maxTouchPoints: 5, platform: "MacIntel", standalone: true }); E([isIosLikeNavigator(), isStandaloneDisplay()]).toEqual([true, true]);
    X.setPwaNavigator({ standalone: false }); const { result, unmount } = RH(() => usePwaInstall());
    await act(async () => { await result.current.promptInstall(); }); E(result.current.isInstalled).toBe(false);
    act(() => { window.dispatchEvent(new Event("appinstalled")); }); await W(() => E(result.current.isInstalled).toBe(true));
    act(() => dm.setMatches(true)); act(() => { window.dispatchEvent(X.makePwaPromptEvent()); }); E(result.current.promptKind).toBeNull();
    unmount(); E(dm.mediaQuery.removeEventListener).toHaveBeenCalled();
  });

  it("AC22.20.3 InstallAppPromptView", async () => {
    const user = userEvent.setup(), promptInstall = vi.fn().mockResolvedValue(undefined);
    const v1 = R(<InstallAppPromptView state={X.makePwaPromptState({ promptInstall })} />);
    await user.click(X.btn("Install app")); E(promptInstall).toHaveBeenCalledTimes(1); v1.unmount();
    const v2 = R(<InstallAppPromptView state={X.makePwaPromptState({ promptKind: "ios", canPrompt: false })} />);
    X.hasTxts("Add Finance Report to Home Screen"); E(S.queryByRole("button", { name: "Install app" })).toBeNull(); v2.unmount();
    E(R(<InstallAppPromptView state={X.makePwaPromptState({ isInstalled: true })} />).container).toBeEmptyDOMElement();
  });
});
// AC-meta.fe-ia-nav.21-24
