"use client";

import { useCallback, useState } from "react";

interface StatementUploaderProps {
    onUploadComplete?: () => void;
    onError?: (error: string) => void;
}

export default function StatementUploader({
    onUploadComplete,
    onError,
}: StatementUploaderProps) {
    const [isDragging, setIsDragging] = useState(false);
    const [file, setFile] = useState<File | null>(null);
    const [institution, setInstitution] = useState("");
    const [uploading, setUploading] = useState(false);
    const [error, setError] = useState<string | null>(null);

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
    }, []);

    const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        const selectedFile = e.target.files?.[0];
        if (selectedFile) validateAndSetFile(selectedFile);
    }, []);

    const validateAndSetFile = (f: File) => {
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
    };

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

            const { apiUpload } = await import("@/lib/api");
            await apiUpload("/api/statements/upload", formData);

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
                />
            </div>

            {/* Error Message */}
            {error && (
                <div className="alert-error">
                    {error}
                </div>
            )}

            {/* Upload Button */}
            <button
                onClick={handleUpload}
                disabled={!file || !institution.trim() || uploading}
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
