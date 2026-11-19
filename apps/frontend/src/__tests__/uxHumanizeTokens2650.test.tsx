import { render as R } from "@testing-library/react";
import { describe, expect as E, it, vi } from "vitest";
import AuditPage from "@/app/(main)/audit/page";
import ChatPage from "@/app/(main)/chat/page";
import HomePage from "@/app/(main)/page";
import PortfolioPage from "@/app/(main)/portfolio/page";
import ReportsPage from "@/app/(main)/reports/page";
import StatementReviewPage from "@/app/(main)/statements/[id]/page";
import UploadPage from "@/app/(main)/upload/page";
import { AdvisorBrief } from "@/components/chat/AdvisorBrief";
import { PackagePanel } from "@/components/reports/CashFlowAndPackagePanels";
import { PackageCover } from "@/components/reports/package/shared";
import { AccountsPanel } from "@/components/settings/SettingsPanels";
import { humanizeWorkflowText } from "@/components/workflow/workflowFormat";
import { apiOperation } from "@/lib/api";
import { formatAccountCodeBadge } from "@/lib/statusLabels";
import { setTestUrl } from "./helpers/nextNavigation";
import * as F from "./helpers/shellTestFixtures";

vi.mock("next/navigation", async () => ({ ...(await import("./helpers/nextNavigation")).nextNavigationMock, useParams: () => ({ id: "stmt-1" }) }));
vi.mock("next/link", async () => (await import("./helpers/shellTestFixtures")).linkMock);
const showToastMock = vi.fn();
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn(), apiOperationDownload: vi.fn(), apiOperationStream: vi.fn() }));
vi.mock("@/lib/aiModels", () => ({ fetchAiModels: vi.fn().mockResolvedValue({ default_model: "gpt-4o", models: [{ id: "gpt-4o", name: "GPT-4o", is_free: true }] }) }));
const mockedPkg = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/usePersonalReportPackage", async (o) => (await import("./helpers/shellTestFixtures")).pkgHookMock(mockedPkg)(o));
const api = vi.mocked(apiOperation);

describe("#2650", () => {
  it.each(F.HUMANIZE_BADGES)("b%#", (c, l) => E(formatAccountCodeBadge(c)).toBe(l));
  it.each(F.HUMANIZE_TEXTS)("t%#", (r, c) => E(humanizeWorkflowText(r)).toBe(c));

  it("cmp", async () => {
    const v1 = R(<AdvisorBrief suggestions={F.HUMANIZE_SUGGESTIONS} />); await F.checkHumanizeBrief(); v1.unmount();
    mockedPkg.mockReturnValue({ contract: null, document: null, packageSnapshots: [], isPackageRefreshing: false, isPackageLoading: true, error: null });
    const v2 = R(<><PackageCover {...F.HUMANIZE_PKG_PROPS} /><PackagePanel filters={F.makeReportFilters({ tab: "package" })} /></>);
    F.checkHumanizePkg(v2.container); v2.unmount();
    F.mockApiMap(api, F.HUMANIZE_ACCOUNTS_ROUTES); R(<AccountsPanel />); await F.checkHumanizeAccounts();
  });

  it.each([HomePage, UploadPage, StatementReviewPage, AuditPage, ReportsPage, PortfolioPage, ChatPage].map((C, i) => [C, ...F.HUMANIZE_SCREENS[i]] as const))("%#", (C, n, u, e) => F.verifyScreenNoJargon(api, u, e, <C />, setTestUrl, n));
});
