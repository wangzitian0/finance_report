// The frontend ratio module — the TS implementation of the shared, cross-language
// ratio/percent standard (#1167 base-package family). Contract:
// common/ratio/contract/ratio.contract.md. Proven consistent with the Python
// reference via the shared conformance vectors (common/ratio/conformance/vectors.json),
// see ratio.conformance.test.ts. Identifier parity enforced by
// tests/tooling/test_ratio_api_parity.py.

export { RatioError, FloatNotAllowedError, UndefinedRatioError } from "./errors";
export { Ratio, PERCENT_DP, PERCENT_ROUNDING, type RatioInput } from "./ratio";
