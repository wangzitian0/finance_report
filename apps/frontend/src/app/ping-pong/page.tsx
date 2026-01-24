"use client";

import { useState, useEffect, useCallback } from "react";

import { apiFetch } from "@/lib/api";

interface PingState {
  state: "ping" | "pong";
  toggle_count: number;
  updated_at: string | null;
}

export default function PingPongPage() {
  const [pingState, setPingState] = useState<PingState | null>(null);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchState = useCallback(async () => {
    try {
      const data = await apiFetch<PingState>("/api/ping");
      setPingState(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  const toggleState = async () => {
    setToggling(true);
    try {
      const data = await apiFetch<PingState>("/api/ping/toggle", { method: "POST" });
      setPingState(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setToggling(false);
    }
  };

  useEffect(() => { fetchState(); }, [fetchState]);

  return (
    <div className="p-6 flex items-center justify-center min-h-[80vh]">
      <div className="card p-8 max-w-md w-full text-center">
        <h1 className="text-2xl font-semibold mb-1">Ping-Pong Demo</h1>
        <p className="text-sm text-muted mb-6">Backend connectivity test</p>

        {loading ? (
          <div className="flex justify-center">
            <div className="w-12 h-12 border-4 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
          </div>
        ) : error ? (
          <div className="p-4 rounded-md bg-[var(--error-muted)] border border-[var(--error)]/30 text-center">
            <p className="text-sm text-[var(--error)]">{error}</p>
            <button onClick={fetchState} className="btn-secondary mt-3">Retry</button>
          </div>
        ) : (
          <>
            <div className={`text-6xl font-black mb-6 ${pingState?.state === "ping" ? "text-[var(--info)]" : "text-[var(--accent)]"}`}>
              {pingState?.state?.toUpperCase()}
            </div>

            <button
              onClick={toggleState}
              disabled={toggling}
              className="btn-primary w-full text-lg py-3"
            >
              {toggling ? "Toggling..." : "Toggle State"}
            </button>

            <div className="mt-6 text-sm text-muted space-y-1">
              <p>Toggle count: <span className="font-mono">{pingState?.toggle_count}</span></p>
              {pingState?.updated_at && (
                <p>Last toggled: <span className="font-mono">{new Date(pingState.updated_at).toLocaleTimeString()}</span></p>
              )}
            </div>
          </>
        )}

        <div className="mt-6 pt-4 border-t border-[var(--border)] text-xs text-muted">
          <p>Backend: FastAPI + PostgreSQL</p>
          <p>Frontend: Next.js + TailwindCSS</p>
        </div>
      </div>
    </div>
  );
}
