"use client";

import { useCallback, useEffect, useId, useState } from "react";

import { fetchAiModels } from "@/lib/aiModels";
import { useToast } from "@/components/ui/Toast";
import { track, ANALYTICS_EVENTS } from "@/lib/analytics";

const STORAGE_KEY = "statement_model_v1";

// Track if we've already shown the toast to avoid spamming
let storageWarningShown = false;

type AiModelOption = {
  id: string;
  name?: string;
  is_free: boolean;
};

function getSafeStorage(key: string): string | null {
  try {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(key);
  } catch (error) {
    console.warn(`[Storage] Failed to read ${key}:`, error);
    return null;
  }
}

function setSafeStorage(
  key: string,
  value: string,
  showToastFn?: (
    msg: string,
    type: "success" | "error" | "warning" | "info",
  ) => void,
): void {
  try {
    if (typeof window === "undefined") return;
    localStorage.setItem(key, value);
  } catch (error) {
    console.warn(`[Storage] Failed to write ${key}:`, error);
    // Show user-facing notification once to inform them their preference wasn't saved
    if (!storageWarningShown && showToastFn) {
      showToastFn(
        "Unable to save your model preference. Your selection is temporary for this session.",
        "warning",
      );
      storageWarningShown = true;
    }
  }
}

function removeSafeStorage(key: string): void {
  try {
    if (typeof window === "undefined") return;
    localStorage.removeItem(key);
  } catch (error) {
    console.warn(`[Storage] Failed to remove ${key}:`, error);
  }
}

function getFileExtension(fileName: string): string {
  return fileName.split(".").pop()?.toLowerCase() || "";
}

// #1208-followup: the Upload page now exposes ONE statement entry plus separate
// CSV and Manual entries (no per-source-class checklist). `kind` lets the same
// uploader back the statement entry (document statements, LLM identifies the
// type) and the CSV entry (non-standard columns, mapped server-side) with the
// right accepted types — without the user pre-classifying bank vs brokerage.
type UploaderKind = "all" | "statement" | "csv";

const KIND_CONFIG: Record<
  UploaderKind,
  { extensions: string[]; acceptAttr: string; typesLabel: string }
> = {
  all: {
    extensions: ["pdf", "csv", "png", "jpg", "jpeg"],
    acceptAttr: ".pdf,.csv,.png,.jpg,.jpeg",
    typesLabel: "PDF, CSV, PNG, or JPG",
  },
  statement: {
    extensions: ["pdf", "png", "jpg", "jpeg"],
    acceptAttr: ".pdf,.png,.jpg,.jpeg",
    typesLabel: "PDF, PNG, or JPG",
  },
  csv: { extensions: ["csv"], acceptAttr: ".csv", typesLabel: "CSV" },
};

interface StatementUploaderProps {
  onUploadComplete?: () => void;
  onError?: (error: string) => void;
  /** Restrict accepted file types for the statement vs CSV entry. Default "all". */
  kind?: UploaderKind;
}

export default function StatementUploader({
  onUploadComplete,
  onError,
  kind = "all",
}: StatementUploaderProps): JSX.Element {
  const uploaderConfig = KIND_CONFIG[kind];
  // Per-instance ids so multiple uploaders (statement + CSV) can coexist on
  // one page without colliding label/datalist associations. useId() returns
  // colon-delimited values (":r1:") that are invalid in CSS selectors, so we
  // strip the colons while keeping the per-instance uniqueness.
  const reactId = useId().replace(/:/g, "");
  const fileInputId = `file-upload-${reactId}`;
  const institutionId = `institution-${reactId}`;
  const banksListId = `banks-list-${reactId}`;
  const aiModelId = `ai-model-${reactId}`;
  const { showToast } = useToast();
  const [isDragging, setIsDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [institution, setInstitution] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [models, setModels] = useState<AiModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [modelLoading, setModelLoading] = useState(true);
  const isCsvFile = file ? getFileExtension(file.name) === "csv" : false;

  useEffect(() => {
    let active = true;
    async function loadModels(): Promise<void> {
      try {
        const data = await fetchAiModels({ modality: "image" });
        if (!active) return;
        setModels(data.models);
        const stored = getSafeStorage(STORAGE_KEY);

        // IMPORTANT: Validate stored model ID against current catalog
        // Provider catalogs can change, so persisted model IDs must be revalidated.
        const isStoredValid =
          stored && data.models.some((m) => m.id === stored);
        const isDefaultValid = data.models.some(
          (m) => m.id === data.default_model,
        );

        if (stored && !isStoredValid) {
          removeSafeStorage(STORAGE_KEY);
        }

        if (isStoredValid) {
          setSelectedModel(stored);
          return;
        }

        if (!isDefaultValid) {
          console.error(
            "[StatementUploader] Default model validation failed:",
            {
              defaultModel: data.default_model,
              availableModels: data.models.map((m) => m.id),
            },
          );
          setError(
            "We couldn't find a default AI model. Refresh and try again.",
          );
          setSelectedModel("");
          return;
        }

        setSelectedModel(data.default_model);
      } catch (error) {
        if (!active) return;
        console.error("[StatementUploader] Failed to load AI models:", error);
        setError("Unable to load AI models. Please try again.");
        setModels([]);
        setSelectedModel("");
      } finally {
        if (active) setModelLoading(false);
      }
    }
    void loadModels();
    return () => {
      active = false;
    };
  }, []);

  const validateAndSetFile = useCallback(
    function validateAndSetFile(f: File): void {
      const validExtensions = new Set(uploaderConfig.extensions);
      const extension = getFileExtension(f.name);
      if (!validExtensions.has(extension)) {
        setError(
          `Invalid file type: .${extension}. Allowed: ${uploaderConfig.typesLabel}`,
        );
        return;
      }
      if (f.size > 10 * 1024 * 1024) {
        setError("File exceeds 10MB limit");
        return;
      }
      setFile(f);
      setError(null);
    },
    [uploaderConfig],
  );

  const handleDragOver = useCallback(function handleDragOver(
    e: React.DragEvent,
  ): void {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback(function handleDragLeave(
    e: React.DragEvent,
  ): void {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    function handleDrop(e: React.DragEvent): void {
      e.preventDefault();
      setIsDragging(false);
      const droppedFile = e.dataTransfer.files[0];
      if (droppedFile) validateAndSetFile(droppedFile);
    },
    [validateAndSetFile],
  );

  const handleFileChange = useCallback(
    function handleFileChange(e: React.ChangeEvent<HTMLInputElement>): void {
      const selectedFile = e.target.files?.[0];
      if (selectedFile) validateAndSetFile(selectedFile);
    },
    [validateAndSetFile],
  );

  async function handleUpload(): Promise<void> {
    if (!file) {
      setError("Please select a file");
      return;
    }

    setUploading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("file", file);
      if (institution.trim()) {
        formData.append("institution", institution.trim());
      }
      if (!isCsvFile && !selectedModel) {
        setError("Please select an AI model");
        return;
      }
      if (!isCsvFile) {
        formData.append("model", selectedModel);
      }

      const { apiOperationUpload } = await import("@/lib/api-client");
      // EPIC-022 AC22.18.3 (#1109): instrument the upload funnel. Only safe,
      // non-PII context (file type) is sent — never the filename or contents.
      track(ANALYTICS_EVENTS.UPLOAD_STARTED, { is_csv: isCsvFile });
      await apiOperationUpload("upload_statement_statements_upload_post", {
        body: formData,
      });
      track(ANALYTICS_EVENTS.UPLOAD_SUCCEEDED, { is_csv: isCsvFile });

      showToast(
        isCsvFile
          ? "Statement uploaded! CSV parsing in progress..."
          : "Statement uploaded! AI parsing in progress...",
        "success",
      );
      setFile(null);
      setInstitution("");
      onUploadComplete?.();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed";
      // EPIC-022 AC22.18.3 (#1109): record the failure with a coarse error
      // category only — never the raw message, filename, or amounts.
      track(ANALYTICS_EVENTS.UPLOAD_FAILED, {
        is_csv: isCsvFile,
        error_category: err instanceof Error ? "error" : "unknown",
      });
      setError(message);
      onError?.(message);
    } finally {
      setUploading(false);
    }
  }

  let dropZoneTone = "hover:border-[var(--border-hover)]";
  if (file) {
    dropZoneTone = "border-[var(--success)] bg-[var(--success-muted)]";
  }
  if (isDragging) {
    dropZoneTone = "border-[var(--accent)] bg-[var(--accent-muted)]";
  }

  const iconTone = file
    ? "bg-[var(--success-muted)]"
    : "bg-[var(--background-muted)]";

  return (
    <div className="space-y-4">
      {/* Drop Zone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`card p-6 text-center cursor-pointer transition-colors ${dropZoneTone}`}
      >
        <input
          type="file"
          accept={uploaderConfig.acceptAttr}
          onChange={handleFileChange}
          className="hidden"
          id={fileInputId}
          data-testid={`uploader-file-${kind}`}
        />
        <label htmlFor={fileInputId} className="cursor-pointer block">
          <div className="flex flex-col items-center">
            <div
              className={`w-10 h-10 rounded-md flex items-center justify-center mb-3 ${iconTone}`}
            >
              {file ? (
                <svg
                  className="w-5 h-5 text-[var(--success)]"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M5 13l4 4L19 7"
                  />
                </svg>
              ) : (
                <svg
                  className="w-5 h-5 text-muted"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                  />
                </svg>
              )}
            </div>
            {file ? (
              <>
                <p className="font-medium">{file.name}</p>
                <p className="text-xs text-muted mt-1">
                  {(file.size / 1024 / 1024).toFixed(2)} MB
                </p>
              </>
            ) : (
              <>
                <p className="font-medium">
                  Drop files here or click to upload
                </p>
                <p className="text-xs text-muted mt-1">
                  {uploaderConfig.typesLabel} (max 10MB)
                </p>
              </>
            )}
          </div>
        </label>
      </div>

      {/* Institution Input */}
      <div>
        <label
          htmlFor={institutionId}
          className="block text-sm font-medium mb-1.5"
        >
          Bank / Institution{" "}
          <span className="text-muted font-normal">(optional)</span>
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
          <option value="DBS" />
          <option value="OCBC" />
          <option value="UOB" />
          <option value="HSBC" />
          <option value="Citibank" />
          <option value="Standard Chartered" />
          <option value="Chase" />
          <option value="Bank of America" />
          <option value="Wells Fargo" />
          <option value="American Express" />
        </datalist>
      </div>

      {/* Error Message */}
      {error && <div className="alert-error">{error}</div>}

      {/* Model Selection */}
      {isCsvFile ? (
        <div className="rounded-md border border-[var(--border)] bg-[var(--background-muted)] px-3 py-2">
          <p className="text-sm font-medium">CSV files are parsed directly</p>
          <p className="text-xs text-muted mt-1">No AI model needed.</p>
        </div>
      ) : (
        <div>
          <label
            htmlFor={aiModelId}
            className="block text-sm font-medium mb-1.5"
          >
            AI Model
          </label>
          <select
            id={aiModelId}
            data-testid={`uploader-model-${kind}`}
            className="input"
            value={selectedModel}
            onChange={(e) => {
              const next = e.target.value;
              setSelectedModel(next);
              if (next) {
                setSafeStorage(STORAGE_KEY, next, showToast);
              }
            }}
            disabled={modelLoading}
            aria-label="AI model"
          >
            {models.length === 0 ? (
              <option value="">No models available</option>
            ) : (
              models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name || model.id} — {model.is_free ? "Free" : "Paid"}
                </option>
              ))
            )}
          </select>
          <p className="text-xs text-muted mt-1">
            Defaults to the configured OCR model. Paid models are available if
            enabled.
          </p>
        </div>
      )}

      {/* Upload Button */}
      <button
        onClick={handleUpload}
        disabled={uploading}
        className="btn-primary w-full flex items-center justify-center gap-2"
      >
        {uploading ? (
          <>
            <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
            Processing...
          </>
        ) : (
          <>
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"
              />
            </svg>
            Upload & Parse Statement
          </>
        )}
      </button>
    </div>
  );
}
