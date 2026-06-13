import { Badge, type BadgeVariant } from "@/components/ui";
import type { DataProvenance } from "@/lib/types";

const PROVENANCE_LABELS: Record<DataProvenance, string> = {
  imported: "Imported",
  manual: "Manual",
  derived: "Derived",
};

const PROVENANCE_VARIANTS: Record<DataProvenance, BadgeVariant> = {
  imported: "success",
  manual: "warning",
  derived: "muted",
};

export function ProvenanceBadge({
  provenance,
  className,
}: {
  provenance?: DataProvenance | null;
  className?: string;
}) {
  if (!provenance) return null;

  const label = PROVENANCE_LABELS[provenance];
  return (
    <Badge
      variant={PROVENANCE_VARIANTS[provenance]}
      className={className}
      aria-label={`Provenance: ${label}`}
    >
      {label}
    </Badge>
  );
}
