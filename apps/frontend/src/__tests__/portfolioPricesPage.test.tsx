import { beforeEach, describe, it, vi } from "vitest";
import { PriceUpdateForm } from "@/components/pricing/PriceUpdateForm";
import { apiOperation } from "@/lib/api";
import * as F from "./helpers/packageTestFixtures";

const showToastMock = vi.fn();
vi.mock("@/components/ui/Toast", () => ({ useToast: () => ({ showToast: showToastMock }) }));
vi.mock("@/lib/api", () => ({ apiOperation: vi.fn() }));

describe("PriceUpdateForm", () => {
  const api = vi.mocked(apiOperation);
  beforeEach(() => { api.mockReset(); showToastMock.mockReset(); });
  it("renders known tickers, adds/removes rows, validates empty submit, and submits updates", () => F.runPriceKnown(api, showToastMock, PriceUpdateForm));
  it("handles text input mode, uppercase currency, date input, errors, and onSuccess", () => F.runPriceText(api, showToastMock, PriceUpdateForm));
});
