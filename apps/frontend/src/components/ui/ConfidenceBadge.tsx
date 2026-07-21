import type { HTMLAttributes } from "react";

import { Badge, type BadgeVariant } from "@/components/ui";

export type ConfidenceTier =
  "TRUSTED" | "HIGH" | "MEDIUM" | "LOW" | "DETERMINISTIC";

interface ConfidenceBadgeProps extends Pick<
  HTMLAttributes<HTMLSpanElement>,
  "className"
> {
  tier: ConfidenceTier;
}

const TIER_VARIANTS: Record<ConfidenceTier, BadgeVariant> = {
  TRUSTED: "success",
  HIGH: "info",
  MEDIUM: "warning",
  LOW: "muted",
  DETERMINISTIC: "success",
};

const TOOLTIP =
  "Deterministic system facts and manual entries are trusted; AI-extracted facts remain low until confirmed.";

export default function ConfidenceBadge({
  tier,
  className,
}: ConfidenceBadgeProps) {
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
