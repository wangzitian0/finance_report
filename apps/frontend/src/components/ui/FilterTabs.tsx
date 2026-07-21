"use client";

interface FilterTabsProps<Option extends string> {
  /** The selectable filter values (rendered verbatim as the button labels). */
  options: readonly Option[];
  /** The currently-active value. */
  value: Option;
  onChange: (value: Option) => void;
  /** Capitalize the label (matches the journal/assets `capitalize` styling). */
  capitalize?: boolean;
  /** When set, renders `role="tablist"`/`role="tab"`/`aria-selected` (accessible tabs). */
  ariaLabel?: string;
  /** Container className override. Defaults to the shared pill-bar styling. */
  className?: string;
}

const CONTAINER_DEFAULT =
  "flex gap-1 bg-[var(--background-muted)] p-1 rounded-lg w-fit";

/**
 * The segmented filter pill-bar repeated across journal / accounts / assets:
 * a row of buttons where the active one gets the card background. Only the
 * button markup (and its active/inactive className) was duplicated; the
 * container styling and a11y wrapper vary per page, so they stay props.
 */
export function FilterTabs<Option extends string>({
  options,
  value,
  onChange,
  capitalize = false,
  ariaLabel,
  className,
}: FilterTabsProps<Option>) {
  return (
    <div
      className={className ?? CONTAINER_DEFAULT}
      {...(ariaLabel ? { role: "tablist", "aria-label": ariaLabel } : {})}
    >
      {options.map((option) => (
        <button
          key={option}
          type="button"
          {...(ariaLabel
            ? { role: "tab", "aria-selected": value === option }
            : {})}
          onClick={() => onChange(option)}
          className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${capitalize ? "capitalize " : ""}${
            value === option
              ? "bg-[var(--background-card)] text-[var(--foreground)]"
              : "text-muted hover:text-[var(--foreground)]"
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
