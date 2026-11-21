import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ParsingAttempts } from "@/components/statements/StatementRuns";
import { mkClassifyRun, mkRun } from "./helpers/statementTestFixtures";

// #3029 item 4: a classify run that ended `partial` has state `succeeded`. The list shows the outcome.
describe("Parsing attempts and the outcome of a classify run (#3029 item 4)", () => {
  const stateOf = (seq: number) => within(screen.getByTestId(`parsing-attempt-${seq}`)).getByTestId(`parsing-attempt-state-${seq}`);

  it("shows Partial for a partial classify run and Succeeded for a full one", () => {
    render(
      <ParsingAttempts
        runs={[
          mkRun({ seq: 1, outcome: null }),
          mkClassifyRun("succeeded", { id: "run-2", seq: 2, outcome: "partial" }),
          mkClassifyRun("succeeded", { id: "run-3", seq: 3, outcome: "classified" }),
          mkClassifyRun("succeeded", { id: "run-4", seq: 4, outcome: null }),
          mkClassifyRun("failed", { id: "run-5", seq: 5, outcome: "timed_out" }),
          mkRun({ id: "run-6", seq: 6, outcome: "partial" }),
        ]}
      />,
    );
    expect([1, 2, 3, 4, 5, 6].map((seq) => stateOf(seq).textContent)).toEqual([
      "Succeeded",
      "Partial",
      "Succeeded",
      "Succeeded",
      "Failed",
      "Succeeded",
    ]);
    expect(stateOf(2).className).not.toContain("--success");
    expect(stateOf(3).className).toContain("--success");
  });
});
