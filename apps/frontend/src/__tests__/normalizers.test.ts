import { describe, it, expect } from "vitest";
import {
  toTransactionViewModel,
  toJournalEntryViewModel,
} from "../lib/normalizers";
import type { Schemas } from "../lib/api-schema";

describe("normalizers", () => {
  describe("toTransactionViewModel", () => {
    it("normalizes AtomicTransactionResponse with default fields", () => {
      const raw: Schemas["AtomicTransactionResponse"] = {
        id: "txn-1",
        account_id: "acc-1",
        statement_id: "stmt-1",
        txn_date: "2026-03-01",
        description: "Salary",
        amount: "1000.00",
        direction: "CREDIT",
        reference: "REF123",
        currency: "SGD",
        confidence_tier: "TRUSTED",
        created_at: "2026-03-01T10:00:00Z",
        updated_at: "2026-03-01T10:00:00Z",
      };

      const vm = toTransactionViewModel(raw);
      expect(vm.id).toBe("txn-1");
      expect(vm.statement_id).toBe("stmt-1");
      expect(vm.txn_date).toBe("2026-03-01");
      expect(vm.description).toBe("Salary");
      expect(vm.amount).toBe("1000.00");
      expect(vm.direction).toBe("CREDIT");
      expect(vm.reference).toBe("REF123");
      expect(vm.currency).toBe("SGD");
      expect(vm.confidence_tier).toBe("TRUSTED");
      expect(vm.balance_after).toBeNull();
      expect(vm.status).toBe("pending");
      expect(vm.created_at).toBe("2026-03-01T10:00:00Z");
      expect(vm.updated_at).toBe("2026-03-01T10:00:00Z");
    });

    it("normalizes BankTransactionSummary with fallback defaults and overrides", () => {
      const raw: Schemas["BankTransactionSummary"] = {
        id: "summary-1",
        description: "Coffee",
        amount: "5.50",
        direction: "DEBIT",
      };

      const vm = toTransactionViewModel(raw, {
        balance_after: "500.00",
        status: "matched",
        confidence: "high",
        confidence_tier: "HIGH",
        confidence_reason: "Keyword match",
        raw_text: "STARBUCKS",
      });

      expect(vm.id).toBe("summary-1");
      expect(vm.statement_id).toBeNull();
      expect(vm.txn_date).toBe("");
      expect(vm.reference).toBeNull();
      expect(vm.currency).toBeNull();
      expect(vm.balance_after).toBe("500.00");
      expect(vm.status).toBe("matched");
      expect(vm.confidence).toBe("high");
      expect(vm.confidence_tier).toBe("HIGH");
      expect(vm.confidence_reason).toBe("Keyword match");
      expect(vm.raw_text).toBe("STARBUCKS");
      expect(vm.created_at).toBeDefined();
      expect(vm.updated_at).toBeDefined();
    });
  });

  describe("toJournalEntryViewModel", () => {
    it("normalizes JournalEntryResponse with mapped lines and total_amount", () => {
      const entry: Schemas["JournalEntryResponse"] = {
        id: "je-1",
        entry_date: "2026-03-15",
        memo: "Reclassification",
        source_type: "MANUAL",
        confidence_tier: "HIGH",
        status: "posted",
        lines: [
          {
            id: "line-1",
            account_id: "acc-1",
            direction: "DEBIT",
            amount: "100.00",
            currency: "SGD",
            fx_rate: "1.0",
          },
          {
            id: "line-2",
            account_id: "acc-2",
            direction: "CREDIT",
            amount: "100.00",
            currency: "SGD",
          },
        ],
        created_at: "2026-03-15T00:00:00Z",
      };

      const vm = toJournalEntryViewModel(entry, "100.00");
      expect(vm.id).toBe("je-1");
      expect(vm.memo).toBe("Reclassification");
      expect(vm.total_amount).toBe("100.00");
      expect(vm.lines).toHaveLength(2);
      expect(vm.lines[0]).toEqual({
        id: "line-1",
        account_id: "acc-1",
        direction: "DEBIT",
        amount: "100.00",
        currency: "SGD",
        fx_rate: "1.0",
      });
      expect(vm.lines[1]).toEqual({
        id: "line-2",
        account_id: "acc-2",
        direction: "CREDIT",
        amount: "100.00",
        currency: "SGD",
        fx_rate: undefined,
      });
    });

    it("handles JournalEntryResponse with empty lines", () => {
      const entry: Schemas["JournalEntryResponse"] = {
        id: "je-2",
        entry_date: "2026-03-15",
        memo: "Empty entry",
        source_type: "MANUAL",
        status: "draft",
        created_at: "2026-03-15T00:00:00Z",
      };

      const vm = toJournalEntryViewModel(entry);
      expect(vm.id).toBe("je-2");
      expect(vm.lines).toEqual([]);
      expect(vm.total_amount).toBeUndefined();
    });
  });
});
