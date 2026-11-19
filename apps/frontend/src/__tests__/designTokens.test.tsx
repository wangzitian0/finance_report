import { render as R, screen as S } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect as E, it } from "vitest";
import { ConfidenceBadge } from "@/components/ui";
import tailwindConfig from "../../tailwind.config";
import { CONFIDENCE_BADGE_CASES, checkDesignTokenMatches } from "./helpers/shellTestFixtures";

const extend = tailwindConfig.theme?.extend as Record<string, unknown>;
const ssot = readFileSync(resolve(process.cwd(), "../../apps/frontend/frontend-patterns.md"), "utf8");
const globals = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

describe("design tokens", () => {
  it("AC16.29.1-2 AC16.30.2 AC22.12.1 AC22.20.4 tokens, SSOT, CSS", () => checkDesignTokenMatches(extend, ssot, globals));
  it.each(CONFIDENCE_BADGE_CASES)("ConfidenceBadge %s", (tier, cls) => {
    R(<ConfidenceBadge tier={tier} />);
    const el = S.getByText(tier); E(el).toHaveClass(cls); E(el.className).not.toMatch(/\b(bg|text)-(green|blue|amber|gray)-/);
  });
});
// AC-meta.fe-app-shell.26-29 AC-meta.fe-app-shell.31 AC-meta.fe-app-shell.35 AC-meta.fe-ia-nav.13 AC-meta.fe-ia-nav.15 AC-meta.fe-ia-nav.18
