import Decimal from "decimal.js";
import { expect, it } from "vitest";
import {
  ExchangeRate,
  FloatNotAllowedError as MF,
  InvalidMoneyPayloadError as MI,
  Money,
  exchange_rate_from_wire as erFrom,
  exchange_rate_to_wire as erTo,
  money_from_wire as mFrom,
  money_to_wire as mTo,
} from "./audit/money";
import {
  FloatNotAllowedError as QF,
  InvalidQuantityPayloadError as QI,
  Quantity,
  quantity_from_wire as qFrom,
  quantity_to_wire as qTo,
} from "./audit/quantity";
import {
  FloatNotAllowedError as RF,
  InvalidRatioPayloadError as RI,
  Ratio,
  ratio_from_wire as rFrom,
  ratio_to_wire as rTo,
} from "./audit/ratio";
const E = expect;
it("test_AC12_31_4_frontend_boundary_codecs_round_trip_json_strings test_AC12_31_4_frontend_boundary_codecs_emit_fixed_point_large_decimals test_AC12_31_4_frontend_boundary_codecs_reject_malformed_payloads", () => {
  const m = new Money("10.50", "usd"),
    r = new ExchangeRate("usd", "sgd", "1.35"),
    ra = new Ratio("0.125"),
    q = new Quantity("2.500000", "shares"),
    big = "123456789012345678901234567890.125";
  E(mTo(m)).toEqual({ amount: "10.5", currency: "USD" });
  E(JSON.parse(JSON.stringify(mTo(m))).amount).toBe("10.5");
  E(mFrom({ amount: "10.50", currency: "USD" }).equals(m)).toBe(true);
  E(erTo(r)).toEqual({ base: "USD", quote: "SGD", rate: "1.35" });
  E(
    erFrom({ base: "USD", quote: "SGD", rate: "1.35" }).rate.equals(
      new Decimal("1.35"),
    ),
  ).toBe(true);
  E([rTo(ra), rFrom("0.125").equals(ra)]).toEqual(["0.125", true]);
  E(qTo(q)).toEqual({ value: "2.5", unit: "shares" });
  E(qFrom({ value: "2.500000", unit: "shares" }).equals(q)).toBe(true);
  E([
    mTo(new Money(`${big}00`, "usd")).amount,
    erTo(new ExchangeRate("usd", "sgd", big)).rate,
    rTo(new Ratio(big)),
    qTo(new Quantity(big, "shares")).value,
  ]).toEqual([big, big, big, big]);
  for (const [fn, arg, err] of [
    [mFrom, { amount: 10.5, currency: "USD" }, MF],
    [mFrom, { amount: "10.50" }, MI],
    [mFrom, null, MI],
    [mFrom, { amount: true, currency: "USD" }, MF],
    [mTo, "10.50", TypeError],
    [erFrom, { base: "USD", quote: "SGD", rate: 1.35 }, MF],
    [erFrom, { base: "USD", quote: "SGD", rate: "bad" }, MI],
    [erTo, "1.35", TypeError],
    [rFrom, 0.125, RF],
    [rFrom, "bad", RI],
    [rFrom, true, RF],
    [rTo, "0.125", TypeError],
    [qFrom, { value: 2.5, unit: "shares" }, QF],
    [qFrom, { value: "2.5" }, QI],
    [qFrom, null, QI],
    [qFrom, { value: true, unit: "shares" }, QF],
    [qFrom, { value: "bad", unit: "shares" }, QI],
    [qTo, "2.5", TypeError],
  ] as [any, any, any][])
    E(() => fn(arg)).toThrow(err);
});
// AC12.31.4
