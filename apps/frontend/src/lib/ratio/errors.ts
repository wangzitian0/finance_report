// Typed ratio errors — the TS mirror of common/ratio/errors.py / src.ratio.errors,
// so the frontend and backend expose the same ratio error surface (#1167).

export class RatioError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RatioError";
  }
}

/** A float (JS number) was supplied where a Decimal is required. */
export class FloatNotAllowedError extends RatioError {
  constructor(message: string) {
    super(message);
    this.name = "FloatNotAllowedError";
  }
}

/** A ratio was requested from a zero whole (part / 0 is undefined). */
export class UndefinedRatioError extends RatioError {
  constructor(message: string) {
    super(message);
    this.name = "UndefinedRatioError";
  }
}

export class InvalidRatioPayloadError extends RatioError {
  constructor(message: string) {
    super(message);
    this.name = "InvalidRatioPayloadError";
  }
}
