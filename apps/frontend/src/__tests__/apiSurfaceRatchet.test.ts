import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

/**
 * AC-meta.public-boundary.4 (#3015, slice 6 of #3009):
 * 1. The API operation count does not grow from the committed baseline.
 * 2. Every operation id referenced in FE components/lib exists in api-operations.ts.
 * A new route must justify its existence by shrinking the surface elsewhere.
 */
const BASELINE_COUNT = 129;

describe("API surface ratchet", () => {
  const operationsSource = readFileSync(
    resolve(__dirname, "../../src/lib/api-operations.ts"),
    "utf-8",
  );

  it("AC-meta.public-boundary.4 operation count does not grow from baseline", () => {
    const re = /"[a-z_]+_[a-z_0-9]+":\s*\{/g;
    const count = (operationsSource.match(re) ?? []).length;
    expect(
      count,
      `API operation count grew from ${BASELINE_COUNT} to ${count}. ` +
        "A new route must shrink the surface elsewhere or have an explicit " +
        "product justification recorded in the PR.",
    ).toBeLessThanOrEqual(BASELINE_COUNT);
  });

  it("AC-meta.public-boundary.4 every FE-referenced operation id exists in api-operations", () => {
    // Collect op ids referenced by FE components (excluding generated + test files)
    const { execSync } = require("child_process");
    const feDir = resolve(__dirname, "../");
    let feSource = "";
    try {
      feSource = execSync(
        `find ${feDir} -name '*.ts' -o -name '*.tsx' | ` +
          `grep -v __tests__ | grep -v api-operations | grep -v api-types | ` +
          `xargs cat 2>/dev/null || true`,
        { encoding: "utf-8", maxBuffer: 10 * 1024 * 1024 },
      );
    } catch {
      feSource = "";
    }

    // Extract quoted op-id-like strings from FE source
    const opIdPattern = /"([a-z]+(?:_[a-z0-9]+)+_(?:get|post|put|delete|patch))"/g;
    const referenced = new Set<string>();
    let match: RegExpExecArray | null;
    while ((match = opIdPattern.exec(feSource)) !== null) {
      referenced.add(match[1]);
    }

    // Extract op ids defined in api-operations.ts
    const defined = new Set<string>();
    const defRe = /"([a-z]+(?:_[a-z0-9]+)+_(?:get|post|put|delete|patch))":\s*\{/g;
    let dm: RegExpExecArray | null;
    while ((dm = defRe.exec(operationsSource)) !== null) {
      defined.add(dm[1]);
    }

    const stale = [...referenced].filter((id) => !defined.has(id));
    expect(
      stale,
      `FE code references these operation ids but they are not in api-operations.ts: ${stale}. ` +
        "Remove the stale references or re-run the codegen chain.",
    ).toEqual([]);
  });
});
