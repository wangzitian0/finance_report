import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import Decimal from "decimal.js";
import { expect, it } from "vitest";
import { Currency, CurrencyMismatchError, ExchangeRate, FloatNotAllowedError, InvalidCurrencyError, ISO_4217_CODES } from "./index";
import { Money, convert } from "./money";
const V = JSON.parse(readFileSync(resolve(__dirname, "../../../../../../common/audit/money/conformance/vectors.json"), "utf-8"));
const M = (a: string, c = "USD") => new Money(a, c), D = (v: string) => new Decimal(v), E = expect;
it("AC-audit.20.1 AC-audit.20.2 AC-audit.19.1 AC-audit.19.2 AC-audit.30.3 money", () => {
E([V.money_quantum, V.default_rounding]).toEqual(["0.01", "ROUND_HALF_EVEN"]);
for (const c of V.rounding) E(M(c.amount).quantize(c.rounding).amount.equals(D(c.expected))).toBe(true);
const rSet = new Set(V.rounding.map((c: any) => c.rounding));
E(V.convert.length).toBeGreaterThan(0);
for (const c of V.convert) { E(rSet.has(c.rounding)).toBe(true); const r = convert(M(c.amount, c.from), new ExchangeRate(c.from, c.to, c.rate), c.rounding); E([r.amount.equals(D(c.expected)), r.currency.code]).toEqual([true, c.to]); }
for (const c of V.currency_normalize) E(new Currency(c.input).code).toBe(c.expected);
for (const bad of V.currency_invalid) E(() => new Currency(bad)).toThrow(InvalidCurrencyError);
E([...ISO_4217_CODES].sort()).toEqual([...V.iso4217].sort());
// @ts-expect-error number rejected
E(() => new Money(10.0, "USD")).toThrow(FloatNotAllowedError);
// @ts-expect-error number rejected
E(() => new ExchangeRate("USD", "EUR", 1.2)).toThrow(FloatNotAllowedError);
E(() => new Money(new Decimal(Infinity), "USD")).toThrow(FloatNotAllowedError);
E(() => new ExchangeRate("USD", "EUR", new Decimal(Infinity))).toThrow(FloatNotAllowedError);
const usd = M("10.00"), sgd = M("10.00", "SGD"), a = M("1"), b = M("2"), rate = new ExchangeRate("usd", "sgd", "1.35");
E([Money.zero("USD").equals(M("0")), usd.add(M("5")).amount.equals(D("15")), usd.subtract(M("2")).amount.equals(D("8")), usd.equals(sgd), a.lessThan(b), a.lessThanOrEqual(b), b.greaterThan(a), b.greaterThanOrEqual(a), a.compareTo(b), String(a)]).toEqual([true, true, true, false, true, true, true, true, -1, "1 USD"]);
E(() => usd.add(sgd)).toThrow();
E(() => a.lessThan(sgd)).toThrow();
E([rate.base.code, rate.quote.code, String(rate), convert(M("100.00"), rate).equals(M("135.00", "SGD")), convert(M("135.00", "SGD"), rate.inverse()).equals(M("100.00"))]).toEqual(["USD", "SGD", "USD/SGD 1.35", true, true]);
E(() => convert(M("100.00", "EUR"), rate)).toThrow(CurrencyMismatchError);
E(() => new ExchangeRate("USD", "SGD", "0")).toThrow();
// @ts-expect-error non-ExchangeRate rejected
E(() => convert(M("100.00"), "1.35")).toThrow(FloatNotAllowedError);
});
// AC2.21.1
