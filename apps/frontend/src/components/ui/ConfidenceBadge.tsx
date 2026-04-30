import type { HTMLAttributes } from "react";

export type ConfidenceTier = "TRUSTED" | "HIGH" | "MEDIUM" | "LOW";

interface ConfidenceBadgeProps extends Pick<HTMLAttributes<HTMLSpanElement>, "className"> {
  tier: ConfidenceTier;
}

const TIER_STYLES: Record<ConfidenceTier, string> = {
  TRUSTED: "bg-green-100 text-green-800",
  HIGH: "bg-blue-100 text-blue-800",
  MEDIUM: "bg-amber-100 text-amber-800",
  LOW: "bg-gray-100 text-gray-700",
};

const TOOLTIP =
  "Manual entries are TRUSTED; AI-extracted are LOW. Source priority: manual > user-confirmed > auto-matched > auto-parsed.";

export default function ConfidenceBadge({ tier, className }: ConfidenceBadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${TIER_STYLES[tier]} ${className ?? ""}`}
      title={TOOLTIP}
    >
      {tier}
    </span>
  );
}
