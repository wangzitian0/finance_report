"use client";

import { useState } from "react";

import { apiDownload } from "@/lib/api";

interface ExportCsvButtonProps {
  path: string;
}

export function ExportCsvButton({ path }: ExportCsvButtonProps) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleExport = async () => {
    setDownloading(true);
    setError(null);
    try {
      const { blob, filename } = await apiDownload(path);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename || "report.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export CSV.");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={handleExport}
        disabled={downloading}
        className="btn-secondary text-sm"
      >
        {downloading ? "Exporting..." : "Export CSV"}
      </button>
      {error && <span className="text-xs text-[var(--error)]">{error}</span>}
    </div>
  );
}
