import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { expect, it } from "vitest";
const SRC = resolve(__dirname, "..");
const read = (r: string) => readFileSync(join(SRC, r), "utf-8");
const walk = (d: string): string[] =>
  readdirSync(d, { withFileTypes: true }).flatMap((e) => {
    const f = join(d, e.name);
    return e.isDirectory() ? walk(f) : /\.(ts|tsx)$/.test(e.name) ? [f] : [];
  });
const LEGACY = [
  "components/assets",
  "components/review",
  "components/advisor",
  "components/ChatPanel.tsx",
  "components/ChatPageClient.tsx",
  "components/statements/ProcessingTransfers.tsx",
];
const EXPECTED = [
  "components/pricing/GuidedEvidenceForm.tsx",
  "components/pricing/PriceUpdateForm.tsx",
  "components/reconciliation/ProcessingTransfers.tsx",
  "components/reconciliation/Stage2ReviewQueue.tsx",
  "components/statements/StatementReview.tsx",
  "components/statements/StatementRuns.tsx",
  "components/chat/AdvisorBrief.tsx",
  "components/chat/ChatPanel.tsx",
  "components/chat/ChatPageClient.tsx",
];
const FORBIDDEN = [
  "@/components/assets/",
  "@/components/review/",
  "@/components/advisor/",
  "@/components/ChatPanel",
  "@/components/ChatPageClient",
  "@/components/statements/ProcessingTransfers",
];
it("FE domain directory boundary (#3123)", () => {
  for (const r of LEGACY) expect(existsSync(join(SRC, r)), r).toBe(false);
  for (const r of EXPECTED) expect(existsSync(join(SRC, r)), r).toBe(true);
  expect(read("components/portfolio/Holdings.tsx")).not.toMatch(
    /export\s+function\s+PriceUpdateForm/,
  );
  const self = resolve(__filename);
  expect(
    walk(SRC)
      .filter((f) => resolve(f) !== self)
      .flatMap((f) => {
        const c = readFileSync(f, "utf-8");
        return FORBIDDEN.filter((p) => c.includes(p)).map(
          (p) => `${f.slice(SRC.length + 1)}: ${p}`,
        );
      }),
  ).toEqual([]);
  const wb = read("components/reconciliation/Workbench.tsx"),
    audit = read("app/(main)/audit/page.tsx");
  expect(wb).toContain('searchParams?.get("run_id")');
  expect(wb).toContain("<Stage2ReviewQueue runId={runIdParam}");
  expect(audit).toContain("/reconciliation?tab=review-queue&run_id=");
  expect(audit).toContain("<Stage2ReviewQueue embedded runId={runId}");
});
