import { SkeletonBlock } from "@/components/ui";

interface ReportPageSkeletonProps {
  label: string;
  sections?: number;
}

export function ReportPageSkeleton({ label, sections = 3 }: ReportPageSkeletonProps) {
  return (
    <div className="p-6" role="status" aria-label={label} aria-live="polite" aria-busy="true">
      <div className="mb-8 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between" aria-hidden="true">
        <div className="space-y-2">
          <SkeletonBlock className="h-7 w-48" />
          <SkeletonBlock className="h-4 w-72 max-w-full" />
        </div>
        <div className="flex gap-2">
          <SkeletonBlock className="h-9 w-32" />
          <SkeletonBlock className="h-9 w-20" />
          <SkeletonBlock className="h-9 w-28" />
        </div>
      </div>

      <div className="mb-6 flex flex-wrap gap-3" aria-hidden="true">
        <SkeletonBlock className="h-16 w-36" />
        <SkeletonBlock className="h-16 w-36" />
        <SkeletonBlock className="h-16 w-28" />
      </div>

      <div className="mb-6 grid gap-4 md:grid-cols-3" aria-hidden="true">
        {Array.from({ length: 3 }).map((_, index) => (
          <div key={index} className="card p-5">
            <SkeletonBlock className="mb-3 h-3 w-24" />
            <SkeletonBlock className="h-7 w-32" />
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3" aria-hidden="true">
        {Array.from({ length: sections }).map((_, sectionIndex) => (
          <div key={sectionIndex} className="card p-5">
            <SkeletonBlock className="mb-4 h-5 w-36" />
            <div className="space-y-3">
              {Array.from({ length: 4 }).map((__, rowIndex) => (
                <div key={rowIndex} className="flex items-center justify-between gap-4 rounded-control bg-surface-muted/50 p-2">
                  <SkeletonBlock className="h-4 w-2/5" />
                  <SkeletonBlock className="h-4 w-24" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
