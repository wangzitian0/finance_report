export class QuantityError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "QuantityError";
  }
}

export class FloatNotAllowedError extends QuantityError {
  constructor(message: string) {
    super(message);
    this.name = "FloatNotAllowedError";
  }
}

export class InvalidUnitError extends QuantityError {
  constructor(message: string) {
    super(message);
    this.name = "InvalidUnitError";
  }
}

export class UnitMismatchError extends QuantityError {
  constructor(message: string) {
    super(message);
    this.name = "UnitMismatchError";
  }
}
