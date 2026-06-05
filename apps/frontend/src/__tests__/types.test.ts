import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import "@/lib/types";
import { it, expect } from "vitest";

it("types module loads", () => {
  expect(true).toBe(true);
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
