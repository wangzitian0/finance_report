import { expect, it } from "vitest";
import {
  checkSeverityColor,
  checkTypeLabel,
  confidenceLabel,
  countLabel,
  currencyCodeOrDash,
  humanizeIdentifier,
  pnlColorClass,
  readinessVariant,
  reportAccountDisplayName,
} from "@/lib/statusLabels";
it("statusLabels (#1609 #1868 S5 #2728)", () => {
  for (const [n, e] of [
    [92, "Good"],
    [85, "Good"],
    [70, "Fair — review advised"],
    [60, "Fair — review advised"],
    [40, "Low — review required"],
  ] as const)
    expect(confidenceLabel(n)).toBe(e);
  for (const [v, e] of [
    ["SGD", "SGD"],
    [null, "—"],
    [undefined, "—"],
  ] as const)
    expect(currencyCodeOrDash(v)).toBe(e);
  expect([
    countLabel(1, "item"),
    countLabel(3, "item"),
    countLabel(0, "blocked", "blocked"),
    countLabel(2, "blocked", "blocked"),
  ]).toEqual(["1 item", "3 items", "0 blocked", "2 blocked"]);
  expect([
    pnlColorClass("10.00"),
    pnlColorClass("-10.00"),
    pnlColorClass("0"),
  ]).toEqual(["text-[var(--success)]", "text-[var(--error)]", ""]);
  for (const [v, e] of [
    ["csv_export", "CSV Export"],
    ["bank-statement", "Bank Statement"],
    [null, "Not recorded"],
    ["", "Not recorded"],
  ] as const)
    expect(humanizeIdentifier(v)).toBe(e);
  expect([
    checkSeverityColor("high"),
    checkSeverityColor("medium"),
    checkSeverityColor("low"),
  ]).toEqual(["text-[var(--error)]", "text-[var(--warning)]", "text-muted"]);
  expect([
    checkTypeLabel("duplicate"),
    checkTypeLabel("transfer_pair"),
    checkTypeLabel("anomaly"),
    checkTypeLabel("manual_review"),
  ]).toEqual(["Duplicate", "Transfer Pair", "Anomaly", "manual_review"]);
  for (const [s, v] of [
    ["ready", "success"],
    ["generated", "success"],
    ["blocked", "error"],
    ["stale", "error"],
    ["processing", "warning"],
    ["draft", "muted"],
    ["none", "info"],
  ] as const)
    expect(readinessVariant(s)).toBe(v);
  expect([
    reportAccountDisplayName("Processing"),
    reportAccountDisplayName("GXS Bank"),
  ]).toEqual(["Transfers in transit", "GXS Bank"]);
});
