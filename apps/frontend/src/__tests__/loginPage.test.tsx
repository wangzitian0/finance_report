import { render as R } from "@testing-library/react";
import { beforeEach, describe, it, vi } from "vitest";
import LoginPage from "@/app/login/page";
import { ANALYTICS_EVENTS, track } from "@/lib/analytics";
import { apiOperation } from "@/lib/api";
import { setUser } from "@/lib/auth";
import * as X from "./helpers/shellTestFixtures";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushMock }) }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
vi.mock("@/lib/auth", () => ({ setUser: vi.fn() }));
vi.mock("@/lib/analytics", async (o) => ({ ...(await o<typeof import("@/lib/analytics")>()), track: vi.fn() }));
const api = vi.mocked(apiOperation), setUserMock = vi.mocked(setUser);
const submit = (email: string, pw: string, btn: string) => { X.chgLbl("Email Address", email); X.chgLbl("Password", pw); X.clkBtn(btn); };

describe("LoginPage", () => {
  beforeEach(() => { api.mockReset(); setUserMock.mockReset(); pushMock.mockReset(); vi.mocked(track).mockReset(); });
  it("login & register submit, SIGNUP, redirect", () => X.runLoginSubmitFlows(api, setUserMock, pushMock, track, ANALYTICS_EVENTS.SIGNUP, () => R(<LoginPage />)));
  it("register controls, mode, password", () => { R(<LoginPage />); X.runLoginControlChecks(); });
  it("error alert & spinner", () => X.runLoginErrorAndSpinner(api, setUserMock, pushMock, submit, () => R(<LoginPage />)));
});
// AC-identity.fe-auth.6-12 AC-identity.fe-auth2.2
