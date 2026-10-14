import type { Schemas } from "./api-schema";

export type TransactionCategory = Schemas["TransactionCategory"];

export interface CategoryOption {
  value: TransactionCategory;
  label: string;
  direction: "IN" | "OUT" | "NEUTRAL";
}

export const TRANSACTION_CATEGORIES = [
  // Income (IN)
  { value: "SALARY", label: "Salary", direction: "IN" },
  { value: "INTEREST", label: "Interest", direction: "IN" },
  { value: "INVESTMENT_INCOME", label: "Investment Income", direction: "IN" },
  { value: "REFUND", label: "Refund", direction: "IN" },
  { value: "OTHER_INCOME", label: "Other Income", direction: "IN" },
  // Expense (OUT)
  { value: "DINING", label: "Dining", direction: "OUT" },
  { value: "GROCERIES", label: "Groceries", direction: "OUT" },
  { value: "TRANSPORT", label: "Transport", direction: "OUT" },
  { value: "HOUSING", label: "Housing", direction: "OUT" },
  { value: "UTILITIES", label: "Utilities", direction: "OUT" },
  { value: "SHOPPING", label: "Shopping", direction: "OUT" },
  { value: "HEALTHCARE", label: "Healthcare", direction: "OUT" },
  { value: "ENTERTAINMENT", label: "Entertainment", direction: "OUT" },
  { value: "TRAVEL", label: "Travel", direction: "OUT" },
  { value: "EDUCATION", label: "Education", direction: "OUT" },
  { value: "INSURANCE", label: "Insurance", direction: "OUT" },
  { value: "FEES", label: "Fees", direction: "OUT" },
  { value: "OTHER_EXPENSE", label: "Other Expense", direction: "OUT" },
  // Balance-sheet / non-P&L (NEUTRAL — fits both IN and OUT)
  { value: "TRANSFER", label: "Transfer", direction: "NEUTRAL" },
  { value: "CARD_REPAYMENT", label: "Card Repayment", direction: "NEUTRAL" },
  { value: "LOAN_PRINCIPAL", label: "Loan Principal", direction: "NEUTRAL" },
  { value: "INVESTMENT_TRADE", label: "Investment Trade", direction: "NEUTRAL" },
] as const satisfies readonly CategoryOption[];

// Compile-time exhaustiveness guard: fails `tsc --noEmit` if any backend
// `TransactionCategory` enum value is missing from `TRANSACTION_CATEGORIES`.
type _CoveredCategories = (typeof TRANSACTION_CATEGORIES)[number]["value"];
type _MissingCategories = Exclude<TransactionCategory, _CoveredCategories>;
const _exhaustivenessCheck: _MissingCategories extends never ? true : never =
  true;
void _exhaustivenessCheck;

export function getCategoriesForDirection(
  direction?: string | null,
): readonly CategoryOption[] {
  const normalized = direction?.toUpperCase();
  if (normalized === "IN") {
    return TRANSACTION_CATEGORIES.filter(
      (item) => item.direction === "IN" || item.direction === "NEUTRAL",
    );
  }
  if (normalized === "OUT") {
    return TRANSACTION_CATEGORIES.filter(
      (item) => item.direction === "OUT" || item.direction === "NEUTRAL",
    );
  }
  return TRANSACTION_CATEGORIES;
}

export function formatCategoryLabel(category?: string | null): string {
  if (!category) return "";
  const normalized = category.trim().toUpperCase().replace(/[\s-]+/g, "_");
  const match = TRANSACTION_CATEGORIES.find(
    (item) =>
      item.value === normalized ||
      item.label.toLowerCase() === category.trim().toLowerCase(),
  );
  return match ? match.label : category;
}
