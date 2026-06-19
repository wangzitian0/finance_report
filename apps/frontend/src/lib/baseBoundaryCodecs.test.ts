import Decimal from "decimal.js";
import { describe, expect, it } from "vitest";

// AC12.31.4
import {
  ExchangeRate,
  FloatNotAllowedError as MoneyFloatNotAllowedError,
  InvalidMoneyPayloadError,
  Money,
  exchange_rate_from_wire,
  exchange_rate_to_wire,
  money_from_wire,
  money_to_wire,
} from "./money";
import {
  FloatNotAllowedError as QuantityFloatNotAllowedError,
  InvalidQuantityPayloadError,
  Quantity,
  quantity_from_wire,
  quantity_to_wire,
} from "./quantity";
import {
  FloatNotAllowedError as RatioFloatNotAllowedError,
  InvalidRatioPayloadError,
  Ratio,
  ratio_from_wire,
  ratio_to_wire,
} from "./ratio";

describe("base-package boundary codecs", () => {
  it("test_AC12_31_4_frontend_boundary_codecs_round_trip_json_strings", () => {
    const money = new Money("10.50", "usd");
    expect(money_to_wire(money)).toEqual({ amount: "10.5", currency: "USD" });
    expect(JSON.parse(JSON.stringify(money_to_wire(money))).amount).toBe("10.5");
    expect(money_from_wire({ amount: "10.50", currency: "USD" }).equals(money)).toBe(true);
    expect(() => money_from_wire({ amount: 10.5, currency: "USD" })).toThrow(MoneyFloatNotAllowedError);
    expect(() => money_from_wire({ amount: "10.50" })).toThrow(InvalidMoneyPayloadError);

    const rate = new ExchangeRate("usd", "sgd", "1.35");
    expect(exchange_rate_to_wire(rate)).toEqual({ base: "USD", quote: "SGD", rate: "1.35" });
    expect(exchange_rate_from_wire({ base: "USD", quote: "SGD", rate: "1.35" }).rate.equals(new Decimal("1.35"))).toBe(
      true,
    );
    expect(() => exchange_rate_from_wire({ base: "USD", quote: "SGD", rate: 1.35 })).toThrow(
      MoneyFloatNotAllowedError,
    );
    expect(() => exchange_rate_from_wire({ base: "USD", quote: "SGD", rate: "not-decimal" })).toThrow(
      InvalidMoneyPayloadError,
    );

    const ratio = new Ratio("0.125");
    expect(ratio_to_wire(ratio)).toBe("0.125");
    expect(ratio_from_wire("0.125").equals(ratio)).toBe(true);
    expect(() => ratio_from_wire(0.125)).toThrow(RatioFloatNotAllowedError);
    expect(() => ratio_from_wire("not-decimal")).toThrow(InvalidRatioPayloadError);

    const quantity = new Quantity("2.500000", "shares");
    expect(quantity_to_wire(quantity)).toEqual({ value: "2.5", unit: "shares" });
    expect(quantity_from_wire({ value: "2.500000", unit: "shares" }).equals(quantity)).toBe(true);
    expect(() => quantity_from_wire({ value: 2.5, unit: "shares" })).toThrow(QuantityFloatNotAllowedError);
    expect(() => quantity_from_wire({ value: "2.5" })).toThrow(InvalidQuantityPayloadError);
  });

  it("test_AC12_31_4_frontend_boundary_codecs_reject_malformed_payloads", () => {
    expect(() => money_from_wire(null)).toThrow(InvalidMoneyPayloadError);
    expect(() => money_from_wire({ amount: true, currency: "USD" })).toThrow(MoneyFloatNotAllowedError);
    expect(() => money_to_wire("10.50" as unknown as Money)).toThrow(TypeError);
    expect(() => exchange_rate_to_wire("1.35" as unknown as ExchangeRate)).toThrow(TypeError);

    expect(() => ratio_from_wire(true)).toThrow(RatioFloatNotAllowedError);
    expect(() => ratio_to_wire("0.125" as unknown as Ratio)).toThrow(TypeError);

    expect(() => quantity_from_wire(null)).toThrow(InvalidQuantityPayloadError);
    expect(() => quantity_from_wire({ value: true, unit: "shares" })).toThrow(QuantityFloatNotAllowedError);
    expect(() => quantity_from_wire({ value: "not-decimal", unit: "shares" })).toThrow(InvalidQuantityPayloadError);
    expect(() => quantity_to_wire("2.5" as unknown as Quantity)).toThrow(TypeError);
  });
});
