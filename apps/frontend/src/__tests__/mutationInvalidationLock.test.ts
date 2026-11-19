import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import { expect, it } from "vitest";
import { MUTATION_INVALIDATION_MATRIX, declaredInvalidations, declaredMutationCountByFile } from "./fixtures/mutationInvalidationMatrix";
const srcRoot = resolve(__dirname, "..");
const walk = (d: string, out: string[] = []): string[] => {
  for (const e of readdirSync(d)) {
    const f = join(d, e), x = f.split(sep).join("/");
    if (statSync(f).isDirectory()) walk(f, out);
    else if (/\.tsx?$/.test(e) && !x.includes("/__tests__/") && !x.includes("/tests/") && !/\.(test|spec)\.tsx?$/.test(x)) out.push(f);
  }
  return out;
};
it("AC-testing.fe-async.3 mutation invalidation matrix lock (#1827)", () => {
  const actual = new Map<string, number>();
  for (const f of walk(srcRoot)) {
    const m = readFileSync(f, "utf-8").match(/\buseMutation\s*[(<]/g);
    if (m?.length) actual.set(relative(srcRoot, f).split(sep).join("/"), m.length);
  }
  const declared = declaredMutationCountByFile();
  for (const [f, n] of actual) expect(declared.get(f), f).toBe(n);
  for (const [f, n] of declared) expect(actual.get(f), f).toBe(n);
  expect(declaredInvalidations("accounts.delete")).toEqual([["accounts"]]);
  expect(() => declaredInvalidations("not-a-flow")).toThrow(/not declared in MUTATION_INVALIDATION_MATRIX/);
  expect(new Set(MUTATION_INVALIDATION_MATRIX.map((r) => r.flow)).size).toBe(MUTATION_INVALIDATION_MATRIX.length);
  for (const r of MUTATION_INVALIDATION_MATRIX) {
    if (r.invalidates.length === 0) expect(r.noInvalidationReason, r.flow).toBeTruthy();
    else for (const k of r.invalidates) expect(k.length, r.flow).toBeGreaterThan(0);
  }
});
