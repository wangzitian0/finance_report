import { beforeEach, describe, it, vi } from "vitest";
import ReportsPage from "@/app/(main)/reports/page";
import StatementDetailPage from "@/app/(main)/statements/[id]/page";
import { SourceEnvelopeConfirmation } from "@/components/statements/StatementReview";
import { apiOperation } from "@/lib/api";
import { setTestUrl } from "./helpers/nextNavigation";
import { renderReviewComponent } from "./helpers/renderReviewComponent";
import * as X from "./helpers/shellTestFixtures";

vi.mock("next/link", async () => (await import("./helpers/shellTestFixtures")).linkMock);
vi.mock("next/navigation", async () => ({ ...(await import("./helpers/nextNavigation")).nextNavigationMock, useParams: vi.fn(() => ({ id: "stmt-2765" })) }));
vi.mock("@/hooks/useBaseCurrency", () => ({ useBaseCurrency: () => ({ baseCurrency: "SGD", loading: false }) }));
vi.mock("@/components/charts/SankeyChart", () => ({ SankeyChart: () => <div>S</div> }));
vi.mock("@/hooks/useCurrencies", () => ({ useCurrencies: () => ({ currencies: ["SGD", "USD"], loading: false }) }));
vi.mock("@/lib/api", async (o) => ({ ...(await o<typeof import("@/lib/api")>()), API_URL: "http://localhost:8000", apiOperation: vi.fn(), apiOperationDownload: vi.fn() }));
const api = vi.mocked(apiOperation);

describe("#2765", () => {
  beforeEach(() => { api.mockReset(); setTestUrl("/reports?tab=cash-flow"); });
  it("cash_bridge, balance, rationale", () =>
    X.runCashFlowAndReview2765(api, <ReportsPage />, () => renderReviewComponent(<StatementDetailPage /> as never), (d, fn) => <SourceEnvelopeConfirmation {...X.checkEnvelope2765Props()} envelopeDraft={d} onDraftChange={fn} />));
});
