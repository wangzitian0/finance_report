import { act, render as R } from "@testing-library/react";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { NeedsConfirmationQueue } from "@/components/audit/AuditPanels";
import UploadPage from "@/app/(main)/upload/page";
import { HomeActionBanner } from "@/components/home/HomeActionBanner";
import { apiOperation } from "@/lib/api";
import { createAppQueryClient } from "@/lib/queryClient";
import * as X from "./helpers/shellTestFixtures";

vi.mock("next/link", async () => (await import("./helpers/shellTestFixtures")).linkMock);
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), useSearchParams: () => new URLSearchParams() }));
vi.mock("@/components/statements/StatementUploader", async () => (await import("./helpers/shellTestFixtures")).uploaderMock("UploadMock"));
vi.mock("@/components/pricing/GuidedEvidenceForm", () => ({ default: () => <div /> }));
const showToastMock = vi.fn();
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));
const api = vi.mocked(apiOperation);

describe("shared query cache", () => {
  beforeEach(() => api.mockReset());
  afterEach(() => vi.useRealTimers());
  it("deduplicates across views & revisits", () => X.runQueryCacheDedupFlow(api, <><HomeActionBanner /><NeedsConfirmationQueue /></>, <UploadPage />, <NeedsConfirmationQueue />));
  it("polls parsing every 3s, stops, invalidates", () => X.runQueryCachePolling(api, act, (c) => R(<UploadPage />, { wrapper: X.clientWrapper(c) }), createAppQueryClient()));
});
