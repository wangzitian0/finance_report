export const formatDateInput = (value: Date): string => {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

export const formatDateDisplay = (value: string | Date): string => {
  const d = typeof value === "string" ? new Date(value + (value.includes("T") ? "" : "T00:00:00")) : value;
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
};

export const formatDateTimeDisplay = (value: string | Date): string => {
  const d = typeof value === "string" ? new Date(value) : value;
  return d.toLocaleString("en-US", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};

export const formatMonthLabel = (value: string): string => {
  const safe = value.includes("T") ? value : value + "T00:00:00";
  return new Date(safe).toLocaleDateString("en-US", { month: "short" });
};

/**
 * A statement/document period as "start to end", or "Parsing..." while
 * either bound is still unknown. Was two near-duplicate local copies
 * (upload/page.tsx used "→", statements/[id]/page.tsx used "to") that had
 * already diverged (#1868 S5) — "to" is the single canonical separator.
 */
export const formatPeriod = (start?: string | null, end?: string | null): string => {
  if (!start || !end) return "Parsing...";
  return `${start} to ${end}`;
};
