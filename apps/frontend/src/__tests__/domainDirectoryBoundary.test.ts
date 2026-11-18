import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const FE_SRC = resolve(__dirname, "..");

function walkTsFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walkTsFiles(full));
    else if (/\.(ts|tsx)$/.test(entry.name)) out.push(full);
  }
  return out;
}

describe("FE domain directory boundary (#3123)", () => {
  it("retires misplaced directories/components and places them in their domain directories", () => {
    const retired = [
      "components/assets",
      "components/review",
      "components/advisor",
      "components/ChatPanel.tsx",
      "components/ChatPageClient.tsx",
      "components/statements/ProcessingTransfers.tsx",
    ];
    for (const rel of retired) {
      expect(existsSync(join(FE_SRC, rel)), `Legacy path still exists: ${rel}`).toBe(false);
    }

    const expected = [
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
    for (const rel of expected) {
      expect(existsSync(join(FE_SRC, rel)), `Canonical domain file missing: ${rel}`).toBe(true);
    }

    const holdingsSrc = readFileSync(join(FE_SRC, "components/portfolio/Holdings.tsx"), "utf-8");
    expect(holdingsSrc).not.toMatch(/export\s+function\s+PriceUpdateForm/);
  });

  it("removes all imports referencing legacy component locations", () => {
    const forbidden = [
      "@/components/assets/",
      "@/components/review/",
      "@/components/advisor/",
      "@/components/ChatPanel",
      "@/components/ChatPageClient",
      "@/components/statements/ProcessingTransfers",
    ];
    const selfPath = resolve(__filename);
    const offenders: string[] = [];
    for (const file of walkTsFiles(FE_SRC)) {
      if (resolve(file) === selfPath) continue;
      const content = readFileSync(file, "utf-8");
      for (const prefix of forbidden) {
        if (content.includes(prefix)) {
          offenders.push(`${file.slice(FE_SRC.length + 1)}: ${prefix}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("wires Stage-2 run_id queue navigation consistently between /reconciliation and /audit", () => {
    const workbenchSrc = readFileSync(join(FE_SRC, "components/reconciliation/Workbench.tsx"), "utf-8");
    expect(workbenchSrc).toContain('searchParams?.get("run_id")');
    expect(workbenchSrc).toContain("<Stage2ReviewQueue runId={runIdParam}");

    const auditSrc = readFileSync(join(FE_SRC, "app/(main)/audit/page.tsx"), "utf-8");
    expect(auditSrc).toContain("/reconciliation?tab=review-queue&run_id=");
    expect(auditSrc).toContain("<Stage2ReviewQueue embedded runId={runId}");
  });
});
