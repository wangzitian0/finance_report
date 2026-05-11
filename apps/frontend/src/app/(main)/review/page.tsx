"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

interface Stage1Statement {
    id: string;
    original_filename: string;
    institution: string;
    confidence_score: number | null;
    status: string;
}

interface Stage1PendingResponse {
    items: Stage1Statement[];
    total: number;
}

interface Stage2Match {
    id: string;
    description?: string;
    status: string;
    match_score: number;
}

interface Stage2QueueResponse {
    pending_matches: Stage2Match[];
}

export default function ReviewPage() {
    const [stage1Items, setStage1Items] = useState<Stage1Statement[]>([]);
    const [stage2Items, setStage2Items] = useState<Stage2Match[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchQueue = useCallback(async () => {
        try {
            const [stage1, stage2] = await Promise.all([
                apiFetch<Stage1PendingResponse>("/api/statements/pending-review"),
                apiFetch<Stage2QueueResponse>("/api/statements/stage2/queue"),
            ]);
            setStage1Items(stage1.items);
            setStage2Items(stage2.pending_matches.filter((match) => match.status === "pending_review"));
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load review queue");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchQueue();
    }, [fetchQueue]);

    const totalPending = stage1Items.length + stage2Items.length;

    if (loading) {
        return (
            <div className="p-6">
                <div className="card p-8 text-center text-muted">
                    <p className="text-sm">Loading review queue...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="p-6">
            <div className="page-header">
                <h1 className="page-title">Review Queue</h1>
                <p className="page-description">
                    {totalPending} pending item{totalPending === 1 ? "" : "s"} across Stage 1 and Stage 2 reviews.
                </p>
            </div>

            {error && <div className="mb-4 alert-error">{error}</div>}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="card">
                    <div className="card-header flex items-center justify-between">
                        <h2 className="text-sm font-medium">Stage 1 Pending Statements</h2>
                        <span className="badge badge-warning">{stage1Items.length}</span>
                    </div>
                    {stage1Items.length === 0 ? (
                        <div className="p-6 text-sm text-muted">No statements pending Stage 1 review.</div>
                    ) : (
                        <div className="divide-y divide-[var(--border)]">
                            {stage1Items.map((statement) => (
                                <Link
                                    key={statement.id}
                                    href={`/statements/${statement.id}/review`}
                                    className="block px-4 py-3 hover:bg-[var(--background-muted)]/50 transition-colors"
                                >
                                    <div className="font-medium text-sm">{statement.original_filename}</div>
                                    <div className="text-xs text-muted">
                                        {statement.institution} • Confidence {statement.confidence_score ?? "—"}%
                                    </div>
                                </Link>
                            ))}
                        </div>
                    )}
                </div>

                <div className="card">
                    <div className="card-header flex items-center justify-between">
                        <h2 className="text-sm font-medium">Stage 2 Pending Matches</h2>
                        <span className="badge badge-warning">{stage2Items.length}</span>
                    </div>
                    {stage2Items.length === 0 ? (
                        <div className="p-6 text-sm text-muted">No matches pending Stage 2 review.</div>
                    ) : (
                        <div className="divide-y divide-[var(--border)]">
                            {stage2Items.slice(0, 10).map((match) => (
                                <div key={match.id} className="px-4 py-3">
                                    <div className="font-medium text-sm">{match.description || "Pending match"}</div>
                                    <div className="text-xs text-muted">Match score: {match.match_score}</div>
                                </div>
                            ))}
                        </div>
                    )}
                    <div className="p-4 border-t border-[var(--border)]">
                        <Link href="/reconciliation/review-queue" className="btn-secondary w-full text-center">
                            Open Stage 2 Review Queue
                        </Link>
                    </div>
                </div>
            </div>
        </div>
    );
}
