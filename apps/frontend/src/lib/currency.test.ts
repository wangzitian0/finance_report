import { describe, it, expect } from 'vitest';
import Decimal from 'decimal.js';
import {
  parseAmount,
  formatAmount,
  sumAmounts,
  subtractAmounts,
  multiplyAmount,
  divideAmount,
  compareAmounts,
  isAmountZero,
  formatCurrency,
} from './currency';

describe('parseAmount', () => {
  describe('valid inputs', () => {
    it('should parse valid numeric strings', () => {
      expect(parseAmount('100').toString()).toBe('100');
      expect(parseAmount('100.50').toString()).toBe('100.5');
      expect(parseAmount('0.01').toString()).toBe('0.01');
      expect(parseAmount('-50.25').toString()).toBe('-50.25');
    });

    it('should parse valid numbers', () => {
      expect(parseAmount(100).toString()).toBe('100');
      expect(parseAmount(100.5).toString()).toBe('100.5');
      expect(parseAmount(0.01).toString()).toBe('0.01');
      expect(parseAmount(-50.25).toString()).toBe('-50.25');
    });

    it('should handle strings with leading/trailing whitespace', () => {
      expect(parseAmount('  100.50  ').toString()).toBe('100.5');
      expect(parseAmount(' 0 ').toString()).toBe('0');
    });

    it('should handle very large values', () => {
      expect(parseAmount('999999999999.99').toString()).toBe('999999999999.99');
      expect(parseAmount(999999999999.99).toString()).toBe('999999999999.99');
    });

    it('should handle very small values', () => {
      expect(parseAmount('0.000001').toString()).toBe('0.000001');
      expect(parseAmount(0.000001).toString()).toBe('0.000001');
    });

    it('should handle scientific notation in strings', () => {
      expect(parseAmount('1e10').toString()).toBe('10000000000');
      expect(parseAmount('1.5e-3').toString()).toBe('0.0015');
    });
  });

  describe('invalid inputs (CR8: strict validation)', () => {
    it('should throw on null', () => {
      expect(() => parseAmount(null as any)).toThrow('parseAmount received null or undefined');
    });

    it('should throw on undefined', () => {
      expect(() => parseAmount(undefined as any)).toThrow('parseAmount received null or undefined');
    });

    it('should throw on empty string', () => {
      expect(() => parseAmount('')).toThrow('parseAmount received an empty string');
    });

    it('should throw on whitespace-only string', () => {
      expect(() => parseAmount('   ')).toThrow('parseAmount received an empty string');
    });

    it('should throw on NaN', () => {
      expect(() => parseAmount(NaN)).toThrow('parseAmount received a non-finite number');
    });

    it('should throw on Infinity', () => {
      expect(() => parseAmount(Infinity)).toThrow('parseAmount received a non-finite number');
      expect(() => parseAmount(-Infinity)).toThrow('parseAmount received a non-finite number');
    });

    it('should throw on invalid type', () => {
      expect(() => parseAmount({} as any)).toThrow('parseAmount received an invalid type');
      expect(() => parseAmount([] as any)).toThrow('parseAmount received an invalid type');
      expect(() => parseAmount(true as any)).toThrow('parseAmount received an invalid type');
    });
  });
});

describe('formatAmount', () => {
  it('should format with default 2 decimals', () => {
    expect(formatAmount(new Decimal(100.5))).toBe('100.50');
    expect(formatAmount('100.5')).toBe('100.50');
    expect(formatAmount(100.5)).toBe('100.50');
  });

  it('should format with custom decimal places', () => {
    expect(formatAmount(new Decimal(100.5), 0)).toBe('101');
    expect(formatAmount(new Decimal(100.5), 1)).toBe('100.5');
    expect(formatAmount(new Decimal(100.5), 3)).toBe('100.500');
  });

  it('should handle rounding correctly', () => {
    expect(formatAmount('100.555', 2)).toBe('100.56');
    expect(formatAmount('100.554', 2)).toBe('100.55');
  });

  it('should format negative values', () => {
    expect(formatAmount('-50.25')).toBe('-50.25');
  });
});

describe('sumAmounts', () => {
  it('should sum empty array to zero', () => {
    expect(sumAmounts([]).toString()).toBe('0');
  });

  it('should sum multiple values', () => {
    expect(sumAmounts([10, 20, 30]).toString()).toBe('60');
    expect(sumAmounts(['10.5', '20.25', '30.75']).toString()).toBe('61.5');
  });

  it('should preserve precision', () => {
    expect(sumAmounts(['0.1', '0.2']).toString()).toBe('0.3');
    expect(sumAmounts([0.1, 0.2]).toString()).toBe('0.3');
  });

  it('should handle negative values', () => {
    expect(sumAmounts([10, -5, 20]).toString()).toBe('25');
  });

  it('should handle mixed types', () => {
    expect(sumAmounts([new Decimal(10), '20', 30]).toString()).toBe('60');
  });
});

describe('subtractAmounts', () => {
  it('should subtract two positive values', () => {
    expect(subtractAmounts(100, 50).toString()).toBe('50');
  });

  it('should handle negative results', () => {
    expect(subtractAmounts(50, 100).toString()).toBe('-50');
  });

  it('should preserve precision', () => {
    expect(subtractAmounts('100.5', '50.25').toString()).toBe('50.25');
  });
});

describe('multiplyAmount', () => {
  it('should multiply two values', () => {
    expect(multiplyAmount(10, 5).toString()).toBe('50');
  });

  it('should preserve precision', () => {
    expect(multiplyAmount('10.5', '2').toString()).toBe('21');
  });
});

describe('divideAmount', () => {
  it('should divide two values', () => {
    expect(divideAmount(100, 5).toString()).toBe('20');
  });

  it('should preserve precision', () => {
    expect(divideAmount('10', '3').toString()).toBe('3.3333333333333333333');
  });
});

describe('compareAmounts', () => {
  it('should return -1 when a < b', () => {
    expect(compareAmounts(10, 20)).toBe(-1);
  });

  it('should return 0 when a = b', () => {
    expect(compareAmounts(10, 10)).toBe(0);
  });

  it('should return 1 when a > b', () => {
    expect(compareAmounts(20, 10)).toBe(1);
  });

  it('should handle decimal precision', () => {
    expect(compareAmounts('100.0001', '100.0002')).toBe(-1);
  });
});

describe('isAmountZero', () => {
  it('should return true for zero', () => {
    expect(isAmountZero(0)).toBe(true);
    expect(isAmountZero('0')).toBe(true);
    expect(isAmountZero('0.00')).toBe(true);
  });

  it('should return true for values within default tolerance (0.01)', () => {
    expect(isAmountZero('0.009')).toBe(true);
    expect(isAmountZero('-0.009')).toBe(true);
  });

  it('should return true for values exactly at tolerance boundary (CR1 fix)', () => {
    // CR1: Changed from lessThan to lessThanOrEqualTo to match backend
    expect(isAmountZero('0.01')).toBe(true);
    expect(isAmountZero('-0.01')).toBe(true);
  });

  it('should return false for values exceeding tolerance', () => {
    expect(isAmountZero('0.011')).toBe(false);
    expect(isAmountZero('-0.011')).toBe(false);
  });

  it('should respect custom tolerance', () => {
    expect(isAmountZero('0.05', 0.1)).toBe(true);
    expect(isAmountZero('0.15', 0.1)).toBe(false);
  });

  it('should handle Decimal objects', () => {
    expect(isAmountZero(new Decimal('0.005'))).toBe(true);
    expect(isAmountZero(new Decimal('0.02'))).toBe(false);
  });
});

describe('formatCurrency', () => {
  it('should format with default SGD currency', () => {
    expect(formatCurrency(100.5)).toBe('SGD 100.50');
  });

  it('should format with custom currency', () => {
    expect(formatCurrency(100.5, 'USD')).toBe('USD 100.50');
  });

  it('should format with custom decimal places', () => {
    expect(formatCurrency(100.5, 'SGD', 0)).toBe('SGD 101');
    expect(formatCurrency(100.5, 'SGD', 3)).toBe('SGD 100.500');
  });

  it('should format negative values', () => {
    expect(formatCurrency(-50.25)).toBe('SGD -50.25');
  });
});
