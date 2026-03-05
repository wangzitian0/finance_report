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
  return new Date(value).toLocaleDateString("en-US", { month: "short" });
};