import { Download, FileJson, Printer, Save } from "lucide-react";

import type { PersonalReportPackageSnapshotSummary } from "@/lib/types";

import { formatSnapshotTimestamp, snapshotDownloadLabel } from "./shared";

export function PackageSnapshotsCard({
  snapshots,
  snapshotError,
  canGenerate,
  generating,
  downloading,
  onGenerate,
  onDownload,
}: {
  snapshots: PersonalReportPackageSnapshotSummary[];
  snapshotError: string | null;
  canGenerate: boolean;
  generating: boolean;
  downloading: string | null;
  onGenerate: () => void;
  onDownload: (
    snapshot: PersonalReportPackageSnapshotSummary,
    format: "json" | "csv",
  ) => void;
}) {
  return (
    <section className="card p-5 mb-6 print:hidden">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="font-semibold">Saved Package Artifacts</h2>
          <p className="mt-1 text-sm text-muted">
            Generate an immutable package snapshot before downloading JSON or CSV.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onGenerate}
            disabled={!canGenerate}
            className="btn-primary inline-flex items-center gap-2 text-sm"
          >
            <Save className="h-4 w-4" aria-hidden="true" />
            {generating ? "Generating..." : "Generate Snapshot"}
          </button>
          <button
            type="button"
            onClick={() => window.print()}
            className="btn-secondary inline-flex items-center gap-2 text-sm"
          >
            <Printer className="h-4 w-4" aria-hidden="true" />
            Print / Save as PDF
          </button>
        </div>
      </div>
      {snapshotError ? (
        <p className="mt-3 text-sm text-[var(--error)]">{snapshotError}</p>
      ) : null}
      <div className="mt-5">
        <h3 className="text-sm font-semibold">Recent Snapshots</h3>
        {snapshots.length ? (
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="text-xs uppercase text-muted">
                <tr>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 pr-4 font-medium">Framework</th>
                  <th className="py-2 pr-4 font-medium">Period</th>
                  <th className="py-2 pr-4 font-medium">Created</th>
                  <th className="py-2 font-medium">Downloads</th>
                </tr>
              </thead>
              <tbody>
                {snapshots.map((snapshot) => (
                  <tr key={snapshot.id} className="border-t border-[var(--border)]">
                    <td className="py-3 pr-4">
                      <span className="badge badge-muted">
                        {snapshot.status === "trusted" ? "Trusted" : "Draft"}
                      </span>
                    </td>
                    <td className="py-3 pr-4 font-mono text-xs">
                      {snapshot.framework_id}
                    </td>
                    <td className="py-3 pr-4 font-mono text-xs">
                      {snapshot.start_date} to {snapshot.end_date}
                    </td>
                    <td className="py-3 pr-4 text-muted">
                      {formatSnapshotTimestamp(snapshot.created_at)}
                    </td>
                    <td className="py-3">
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => onDownload(snapshot, "json")}
                          disabled={downloading === `${snapshot.id}:json`}
                          className="btn-secondary inline-flex items-center gap-2 text-xs"
                          aria-label={snapshotDownloadLabel(snapshot, "JSON")}
                        >
                          <FileJson className="h-4 w-4" aria-hidden="true" />
                          JSON
                        </button>
                        <button
                          type="button"
                          onClick={() => onDownload(snapshot, "csv")}
                          disabled={downloading === `${snapshot.id}:csv`}
                          className="btn-secondary inline-flex items-center gap-2 text-xs"
                          aria-label={snapshotDownloadLabel(snapshot, "CSV")}
                        >
                          <Download className="h-4 w-4" aria-hidden="true" />
                          CSV
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-3 text-sm text-muted">No saved package snapshots yet.</p>
        )}
      </div>
    </section>
  );
}
