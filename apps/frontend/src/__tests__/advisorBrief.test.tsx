import { render as R, screen as S, within } from "@testing-library/react";
import { expect as E, it, vi } from "vitest";
import { AdvisorBrief, safeAdvisorHref } from "@/components/chat/AdvisorBrief";
import routeMap from "@/lib/route-map.json";
import * as X from "./helpers/shellTestFixtures";

vi.mock("next/link", async () => (await import("./helpers/shellTestFixtures")).linkMock);

it("AC21.3.2 cards & safe routes", () => {
  R(<AdvisorBrief suggestions={X.ADVISOR_SUGGESTIONS_5} />);
  X.checkAdvisorBriefCardsDom();
});

it("AC21.3.2 dup keys & safeAdvisorHref", () => {
  const err = vi.spyOn(console, "error").mockImplementation(() => undefined);
  try {
    R(<AdvisorBrief suggestions={[{ basis: "b-blocked", confidence_tier: "blocked", source_refs: ["workflow.status", "workflow.status"], limitation: "l-blocked", next_action_href: "/reports/package" }]} />);
    E(within(S.getByTestId("advisor-brief-card-0")).getAllByText("Workflow Status")).toHaveLength(2);
    E(err.mock.calls.some((c) => c.some((a) => String(a).includes("same key")))).toBe(false);
  } finally { err.mockRestore(); }
  X.checkAdvisorBriefAllRoutes(safeAdvisorHref, routeMap.routes);
});
// AC-advisor.fe-remainder-chat.2
