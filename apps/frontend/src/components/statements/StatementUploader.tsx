"use client";

import { useCallback, useEffect, useState } from "react";

import { fetchAiModels } from "@/lib/aiModels";
import { useToast } from "@/components/ui/Toast";

function getSafeStorage(key: string): string | null {
    try {
        if (typeof window === "undefined") return null;
        return localStorage.getItem(key);
    } catch (error) {
        console.warn(`[Storage] Failed to read ${key}:`, error);
        return null;
    }
}

function setSafeStorage(key: string, value: string): void {
    try {
        if (typeof window === "undefined") return;
        localStorage.setItem(key, value);
    } catch (error) {
        console.warn(`[Storage] Failed to write ${key}:`, error);
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

interface StatementUploaderProps {
    onUploadComplete?: () => void;
    onError?: (error: string) => void;
}

export default function StatementUploader({
    onUploadComplete,
    onError,
}: StatementUploaderProps) {
    const { showToast } = useToast();
    const [isDragging, setIsDragging] = useState(false);
    const [file, setFile] = useState<File | null>(null);
    const [institution, setInstitution] = useState("");
    const [uploading, setUploading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [models, setModels] = useState<{ id: string; name?: string; is_free: boolean }[]>([]);
    const [selectedModel, setSelectedModel] = useState<string>("");
    const [modelLoading, setModelLoading] = useState(true);

    useEffect(() => {
        let active = true;
        const loadModels = async () => {
            try {
                const data = await fetchAiModels({ modality: "image" });
                if (!active) return;
                setModels(data.models);
                const stored = getSafeStorage("statement_model_v1");
                
                // IMPORTANT: Validate stored model ID against current catalog
                // OpenRouter periodically removes models (e.g., Gemini 2.0 → 3.0 upgrade)
                // If stored ID is invalid/stale, fall back to default to prevent parsing failures
                const isStoredValid = stored && data.models.some((m) => m.id === stored);
                let preferred = isStoredValid ? stored : data.default_model;
                
                // Double-check preferred model exists (handles race: default_model not in filtered catalog)
                if (!data.models.some((m) => m.id === preferred)) {
                    preferred = data.models[0]?.id || "";
                }
                
                // Clear invalid localStorage entry to prevent future issues
                // User will see the new default model selected on next page load
                if (stored && !isStoredValid) {
                    removeSafeStorage("statement_model_v1");
                }
                
                setSelectedModel(preferred);
            } catch (error) {
                if (!active) return;
                console.error("[StatementUploader] Failed to load AI models:", error);
                setError("Unable to load AI models. Using server default.");
                setModels([]);
                setSelectedModel("");
            } finally {
                if (active) setModelLoading(false);
            }
        };
        void loadModels();
        return () => {
            active = false;
        };
    }, []);

    const validateAndSetFile = useCallback((f: File) => {
        const validExtensions = ["pdf", "csv", "png", "jpg", "jpeg"];
        const ext = f.name.split(".").pop()?.toLowerCase() || "";
        if (!validExtensions.includes(ext)) {
            setError(`Invalid file type: .${ext}. Allowed: PDF, CSV, PNG, JPG`);
            return;
        }
        if (f.size > 10 * 1024 * 1024) {
            setError("File exceeds 10MB limit");
            return;
        }
        setFile(f);
        setError(null);
    }, []);

    const handleDragOver = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(true);
    }, []);

    const handleDragLeave = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
    }, []);

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        const droppedFile = e.dataTransfer.files[0];
        if (droppedFile) validateAndSetFile(droppedFile);
    }, [validateAndSetFile]);

    const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        const selectedFile = e.target.files?.[0];
        if (selectedFile) validateAndSetFile(selectedFile);
    }, [validateAndSetFile]);

    const handleUpload = async () => {
        if (!file || !institution.trim()) {
            setError("Please select a file and enter the institution name");
            return;
        }

        setUploading(true);
        setError(null);

        try {
            const formData = new FormData();
            formData.append("file", file);
            formData.append("institution", institution.trim());
            if (selectedModel) {
                formData.append("model", selectedModel);
            }

            const { apiUpload } = await import("@/lib/api");
            await apiUpload("/api/statements/upload", formData);

            showToast("Statement uploaded! AI parsing in progress...", "success");
            setFile(null);
            setInstitution("");
            onUploadComplete?.();
        } catch (err) {
            const message = err instanceof Error ? err.message : "Upload failed";
            setError(message);
            onError?.(message);
        } finally {
            setUploading(false);
        }
    };

    return (
        <div className="space-y-4">
            {/* Drop Zone */}
            <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                className={`card p-6 text-center cursor-pointer transition-colors ${isDragging
                    ? "border-[var(--accent)] bg-[var(--accent-muted)]"
                    : file
                        ? "border-[var(--success)] bg-[var(--success-muted)]"
                        : "hover:border-[var(--border-hover)]"
                    }`}
            >
                <input
                    type="file"
                    accept=".pdf,.csv,.png,.jpg,.jpeg"
                    onChange={handleFileChange}
                    className="hidden"
                    id="file-upload"
                />
                <label htmlFor="file-upload" className="cursor-pointer block">
                    <div className="flex flex-col items-center">
                        <div className={`w-10 h-10 rounded-md flex items-center justify-center mb-3 ${file ? "bg-[var(--success-muted)]" : "bg-[var(--background-muted)]"
                            }`}>
                            {file ? (
                                <svg className="w-5 h-5 text-[var(--success)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                </svg>
                            ) : (
                                <svg className="w-5 h-5 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                                </svg>
                            )}
                        </div>
                        {file ? (
                            <>
                                <p className="font-medium">{file.name}</p>
                                <p className="text-xs text-muted mt-1">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                            </>
                        ) : (
                            <>
                                <p className="font-medium">Drop files here or click to upload</p>
                                <p className="text-xs text-muted mt-1">PDF, CSV, PNG, or JPG (max 10MB)</p>
                            </>
                        )}
                    </div>
                </label>
            </div>

            {/* Institution Input */}
            <div>
                <label htmlFor="institution" className="block text-sm font-medium mb-1.5">
                    Bank / Institution
                </label>
                <input
                    type="text"
                    id="institution"
                    value={institution}
                    onChange={(e) => setInstitution(e.target.value)}
                    placeholder="e.g., DBS, OCBC, UOB, Chase"
                    className="input"
                    list="banks-list"
                />
                <datalist id="banks-list">
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
            {error && (
                <div className="alert-error">
                    {error}
                </div>
            )}

            {/* Model Selection */}
            <div>
                <label htmlFor="ai-model" className="block text-sm font-medium mb-1.5">
                    AI Model
                </label>
                <select
                    id="ai-model"
                    className="input"
                    value={selectedModel}
                    onChange={(e) => {
                        const next = e.target.value;
                        setSelectedModel(next);
                        if (next) {
                            setSafeStorage("statement_model_v1", next);
                        }
                    }}
                    disabled={modelLoading}
                    aria-label="AI model"
                >
                    {models.length === 0 ? (
                        <option value="">Default (server)</option>
                    ) : (
                        models.map((model) => (
                            <option key={model.id} value={model.id}>
                                {model.name || model.id} — {model.is_free ? "Free" : "Paid"}
                            </option>
                        ))
                    )}
                </select>
                <p className="text-xs text-muted mt-1">
                    Defaults to the configured free model. Paid models are available if enabled in OpenRouter.
                </p>
            </div>

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
