import { readdirSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

import { MONEY_VALUE_CONTRACT } from "@/lib/types";
import { it, expect } from "vitest";

it("types module loads", () => {
  expect(MONEY_VALUE_CONTRACT).toBe("decimal-string");
});

it("AC2.8.2 keeps frontend monetary API fields Decimal-serializable instead of bare number", () => {
  const typesSource = readFileSync(resolve(__dirname, "../lib/types.ts"), "utf8");
  const forbiddenBareNumberFields = [
    "balance?: number",
    "amount: number",
    "total_amount?: number",
    "total_amount: number",
    "opening_balance?: number",
    "closing_balance?: number",
  ];

  for (const field of forbiddenBareNumberFields) {
    expect(typesSource).not.toContain(field);
  }

  expect(typesSource).toContain("export type DecimalValue = string;");
  expect(typesSource).not.toContain("export type DecimalValue = string | number;");
});

function sourceFilesUnder(relativePath: string): string[] {
  const root = resolve(__dirname, "..", relativePath);
  const files: string[] = [];
  const visit = (path: string) => {
    const stat = statSync(path);
    if (stat.isDirectory()) {
      for (const entry of readdirSync(path)) {
        visit(resolve(path, entry));
      }
      return;
    }
    if (/\.(ts|tsx)$/.test(path) && !path.endsWith(".test.tsx") && !path.endsWith(".test.ts")) {
      files.push(path);
    }
  };
  visit(root);
  return files;
}

it("AC2.8.2 keeps page and component money contracts from widening to number|string", () => {
  const moneyFieldNames = [
    "amount",
    "balance",
    "cost",
    "credit",
    "debit",
    "fairValue",
    "fee",
    "gain",
    "income",
    "marketValue",
    "price",
    "total",
    "value",
  ];
  const forbiddenPattern = new RegExp(
    `\\b(?:[A-Za-z0-9_]*_)?(?:${moneyFieldNames.join("|")})(?:_[A-Za-z0-9_]+)?\\??\\s*:\\s*(?:number\\s*\\|\\s*string|string\\s*\\|\\s*number)`,
    "i",
  );
  const offenders = [...sourceFilesUnder("app"), ...sourceFilesUnder("components")]
    .filter((file) => forbiddenPattern.test(readFileSync(file, "utf8")))
    .map((file) => file.replace(resolve(__dirname, "..") + "/", ""));

  expect(offenders).toEqual([]);
});
