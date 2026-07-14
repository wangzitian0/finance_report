// #1827 G-no-undeclared-mutations — structural lock on the invalidation
// matrix.
//
// Scans the real `src/**/*.{ts,tsx}` tree (node fs, tests excluded) for
// `useMutation` call sites and reds on any disagreement with
// MUTATION_INVALIDATION_MATRIX: a brand-new mutation without a matrix row, a
// removed/moved mutation whose stale row lingers, or a miscounted file all
// fail here. Red-team: add `useMutation({...})` in a scratch src file -> this
// suite reds until the matrix declares it.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  MUTATION_INVALIDATION_MATRIX,
  declaredMutationCountByFile,
} from "@/lib/queryInvalidation";

const here = dirname(fileURLToPath(import.meta.url));
const srcRoot = resolve(here, "..");

const CALL_SITE_RE = /\buseMutation\s*[(<]/g;

function isExcluded(path: string): boolean {
  const posix = path.split(sep).join("/");
  return (
    posix.includes("/__tests__/") ||
    posix.includes("/tests/") ||
    /\.(test|spec)\.tsx?$/.test(posix)
  );
}

function walkSourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walkSourceFiles(full, out);
    } else if (/\.tsx?$/.test(entry) && !isExcluded(full)) {
      out.push(full);
    }
  }
  return out;
}

function actualMutationCountByFile(): Map<string, number> {
  const counts = new Map<string, number>();
  for (const file of walkSourceFiles(srcRoot)) {
    const matches = readFileSync(file, "utf-8").match(CALL_SITE_RE);
    if (matches && matches.length > 0) {
      counts.set(relative(srcRoot, file).split(sep).join("/"), matches.length);
    }
  }
  return counts;
}

describe("mutation invalidation matrix lock (#1827 G-no-undeclared-mutations)", () => {
  it("AC-testing.fe-async.3 every useMutation call site in src/ has a matrix row", () => {
    const actual = actualMutationCountByFile();
    const declared = declaredMutationCountByFile();

    for (const [file, count] of actual) {
      expect(
        declared.get(file),
        `${file} has ${count} useMutation call site(s); declare each flow in ` +
          "MUTATION_INVALIDATION_MATRIX (src/lib/queryInvalidation.ts)",
      ).toBe(count);
    }
    for (const [file, count] of declared) {
      expect(
        actual.get(file),
        `${file} declares ${count} matrix row(s) but has no matching ` +
          "useMutation call sites — remove or update the stale declaration",
      ).toBe(count);
    }
  });

  it("AC-testing.fe-async.3 flows are unique and empty invalidations carry a reason", () => {
    const flows = MUTATION_INVALIDATION_MATRIX.map((r) => r.flow);
    expect(new Set(flows).size).toBe(flows.length);

    for (const rule of MUTATION_INVALIDATION_MATRIX) {
      if (rule.invalidates.length === 0) {
        expect(
          rule.noInvalidationReason,
          `flow '${rule.flow}' invalidates nothing — declare why`,
        ).toBeTruthy();
      } else {
        for (const key of rule.invalidates) {
          expect(key.length, `flow '${rule.flow}' declares an empty query key`).toBeGreaterThan(0);
        }
      }
    }
  });
});
