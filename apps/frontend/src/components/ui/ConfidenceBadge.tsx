import type { HTMLAttributes } from "react";

import { Badge, type BadgeVariant } from "@/components/ui";

export type ConfidenceTier = "TRUSTED" | "HIGH" | "MEDIUM" | "LOW";

interface ConfidenceBadgeProps extends Pick<HTMLAttributes<HTMLSpanElement>, "className"> {
  tier: ConfidenceTier;
}

const TIER_VARIANTS: Record<ConfidenceTier, BadgeVariant> = {
  TRUSTED: "success",
  HIGH: "info",
  MEDIUM: "warning",
  LOW: "muted",
};

const TOOLTIP =
  "Manual entries are TRUSTED; AI-extracted are LOW. Source priority: manual > user-confirmed > auto-matched > auto-parsed.";

export default function ConfidenceBadge({ tier, className }: ConfidenceBadgeProps) {
  return (
    <Badge
      variant={TIER_VARIANTS[tier]}
      className={`rounded-pill font-semibold ${className ?? ""}`}
      title={TOOLTIP}
    >
      {tier}
    </Badge>
  );
}
