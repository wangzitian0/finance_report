"use client";

import { useCallback, useId, useState } from "react";

import { useToast } from "@/components/ui/Toast";
import { track, ANALYTICS_EVENTS } from "@/lib/analytics";

const BANK_SUGGESTIONS = ["DBS", "OCBC", "UOB", "HSBC", "Citibank", "Standard Chartered", "Chase", "Bank of America", "Wells Fargo", "American Express"];

function getFileExtension(fileName: string): string {
  return fileName.split(".").pop()?.toLowerCase() || "";
}

type UploaderKind = "all" | "statement" | "csv";

const KIND_CONFIG: Record<UploaderKind, { extensions: string[]; acceptAttr: string; typesLabel: string }> = {
  all: { extensions: ["pdf", "csv", "png", "jpg", "jpeg"], acceptAttr: ".pdf,.csv,.png,.jpg,.jpeg", typesLabel: "PDF, CSV, PNG, or JPG" },
  statement: { extensions: ["pdf", "png", "jpg", "jpeg"], acceptAttr: ".pdf,.png,.jpg,.jpeg", typesLabel: "PDF, PNG, or JPG" },
  csv: { extensions: ["csv"], acceptAttr: ".csv", typesLabel: "CSV" },
};

interface StatementUploaderProps {
  onUploadComplete?: () => void;
  onError?: (error: string) => void;
  kind?: UploaderKind;
}

export default function StatementUploader({ onUploadComplete, onError, kind = "all" }: StatementUploaderProps): JSX.Element {
  const uploaderConfig = KIND_CONFIG[kind];
  const reactId = useId().replace(/:/g, "");
  const fileInputId = `file-upload-${reactId}`;
  const institutionId = `institution-${reactId}`;
  const banksListId = `banks-list-${reactId}`;
  const { showToast } = useToast();
  const [isDragging, setIsDragging] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [institution, setInstitution] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isCsvFile =
    kind === "csv" || (files.length > 0 && files.every((f) => getFileExtension(f.name) === "csv"));

  const validateAndSetFiles = useCallback(
    (incoming: FileList | File[]): void => {
      const selected = Array.from(incoming);
      if (selected.length === 0) return;
      for (const f of selected) {
        const extension = getFileExtension(f.name);
        if (!uploaderConfig.extensions.includes(extension)) {
          setError(`Invalid file type: .${extension}. Allowed: ${uploaderConfig.typesLabel}`);
          return;
        }
        if (f.size > 10 * 1024 * 1024) {
          setError("File exceeds 10MB limit");
          return;
        }
      }
      setFiles(selected);
      setError(null);
    },
    [uploaderConfig],
  );

  async function handleUpload(): Promise<void> {
    if (files.length === 0) {
      setError("Please select a file");
      return;
    }
    setUploading(true);
    setError(null);

    try {
      const { apiOperationUpload } = await import("@/lib/api");
      for (const currentFile of files) {
        const currentIsCsv = getFileExtension(currentFile.name) === "csv";
        const formData = new FormData();
        formData.append("file", currentFile);
        if (institution.trim()) formData.append("institution", institution.trim());

        track(ANALYTICS_EVENTS.UPLOAD_STARTED, { is_csv: currentIsCsv });
        await apiOperationUpload("upload_statement_statements_post", { body: formData });
        track(ANALYTICS_EVENTS.UPLOAD_SUCCEEDED, { is_csv: currentIsCsv });
      }

      showToast(
        files.length > 1
          ? `${files.length} statements uploaded! Parsing in progress...`
          : isCsvFile
            ? "Statement uploaded! CSV parsing in progress..."
            : "Statement uploaded! AI parsing in progress...",
        "success",
      );
      setFiles([]);
      setInstitution("");
      onUploadComplete?.();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed";
      track(ANALYTICS_EVENTS.UPLOAD_FAILED, { is_csv: isCsvFile, error_category: err instanceof Error ? "error" : "unknown" });
      setError(message);
      onError?.(message);
    } finally {
      setUploading(false);
    }
  }

  const dropZoneTone = isDragging
    ? "border-[var(--accent)] bg-[var(--accent-muted)]"
    : files.length > 0
      ? "border-[var(--success)] bg-[var(--success-muted)]"
      : "hover:border-[var(--border-hover)]";

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={(e) => { e.preventDefault(); setIsDragging(false); }}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          if (e.dataTransfer.files.length > 0) validateAndSetFiles(e.dataTransfer.files);
        }}
        className={`card p-6 text-center cursor-pointer transition-colors ${dropZoneTone}`}
      >
        <input
          type="file"
          multiple
          accept={uploaderConfig.acceptAttr}
          onChange={(e) => { if (e.target.files && e.target.files.length > 0) validateAndSetFiles(e.target.files); }}
          className="hidden"
          id={fileInputId}
          data-testid={`uploader-file-${kind}`}
        />
        <label htmlFor={fileInputId} className="cursor-pointer block">
          <div className="flex flex-col items-center">
            <div className={`w-10 h-10 rounded-md flex items-center justify-center mb-3 ${files.length > 0 ? "bg-[var(--success-muted)]" : "bg-[var(--background-muted)]"}`}>
              {files.length > 0 ? (
                <svg className="w-5 h-5 text-[var(--success)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              ) : (
                <svg className="w-5 h-5 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
              )}
            </div>
            {files.length === 1 ? (
              <>
                <p className="font-medium">{files[0].name}</p>
                <p className="text-xs text-muted mt-1">{(files[0].size / 1024 / 1024).toFixed(2)} MB</p>
              </>
            ) : files.length > 1 ? (
              <>
                <p className="font-medium">{files.map((f) => f.name).join(", ")}</p>
                <p className="text-xs text-muted mt-1">
                  {files.length} files · {(files.reduce((sum, f) => sum + f.size, 0) / 1024 / 1024).toFixed(2)} MB
                </p>
              </>
            ) : (
              <>
                <p className="font-medium">Drop files here or click to upload</p>
                <p className="text-xs text-muted mt-1">{uploaderConfig.typesLabel} (max 10MB)</p>
              </>
            )}
          </div>
        </label>
      </div>

      <div>
        <label htmlFor={institutionId} className="block text-sm font-medium mb-1.5">
          Bank / Institution <span className="text-muted font-normal">(optional)</span>
        </label>
        <input
          type="text"
          id={institutionId}
          data-testid={`uploader-institution-${kind}`}
          value={institution}
          onChange={(e) => setInstitution(e.target.value)}
          placeholder="Auto-detected from document, or enter manually"
          className="input"
          list={banksListId}
        />
        <datalist id={banksListId}>
          {BANK_SUGGESTIONS.map((bank) => <option key={bank} value={bank} />)}
        </datalist>
      </div>

      {error && <div className="alert-error">{error}</div>}

      {isCsvFile && (
        <div className="rounded-md border border-[var(--border)] bg-[var(--background-muted)] px-3 py-2">
          <p className="text-sm font-medium">CSV files are parsed directly</p>
          <p className="text-xs text-muted mt-1">No AI model needed.</p>
        </div>
      )}

      <button onClick={handleUpload} disabled={uploading} className="btn-primary w-full flex items-center justify-center gap-2">
        {uploading ? (
          <>
            <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
            Processing...
          </>
        ) : (
          <>
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
            Upload & Parse Statement
          </>
        )}
      </button>
    </div>
  );
}
