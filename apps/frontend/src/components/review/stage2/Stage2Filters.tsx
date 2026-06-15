import { InfoHint } from "@/components/ui/InfoHint";

interface Stage2FiltersProps {
    checkTypeFilter: string;
    statusFilter: string;
    severityFilter: string[];
    minScore: number;
    onToggleSeverity: (severity: string) => void;
    onCheckTypeChange: (value: string) => void;
    onStatusChange: (value: string) => void;
    onMinScoreChange: (value: number) => void;
}

export function Stage2Filters({
    checkTypeFilter,
    statusFilter,
    severityFilter,
    minScore,
    onToggleSeverity,
    onCheckTypeChange,
    onStatusChange,
    onMinScoreChange,
}: Stage2FiltersProps) {
    return (
        <div className="mb-6 grid grid-cols-1 md:grid-cols-4 gap-4 bg-[var(--background-card)] p-4 rounded-lg border border-[var(--border)]">
            <div className="space-y-2">
                <label className="text-xs font-medium text-muted uppercase">Severity</label>
                <div className="flex flex-wrap gap-2">
                    {["high", "medium", "low"].map(s => (
                        <button
                            key={s}
                            onClick={() => onToggleSeverity(s)}
                            className={`px-2 py-1 text-xs rounded-full border transition-colors ${
                                severityFilter.includes(s)
                                    ? "bg-[var(--accent)] text-white border-[var(--accent)]"
                                    : "bg-[var(--background)] text-muted border-[var(--border)] hover:border-[var(--accent)]"
                            }`}
                        >
                            {s.toUpperCase()}
                        </button>
                    ))}
                </div>
            </div>

            <div className="space-y-2">
                <label className="text-xs font-medium text-muted uppercase">Check Type</label>
                <select
                    className="input text-sm py-1"
                    value={checkTypeFilter}
                    onChange={(e) => onCheckTypeChange(e.target.value)}
                >
                    <option value="">All Types</option>
                    <option value="duplicate">Duplicate</option>
                    <option value="transfer_pair">Transfer Pair</option>
                    <option value="anomaly">Anomaly</option>
                </select>
            </div>

            <div className="space-y-2">
                <label className="text-xs font-medium text-muted uppercase">Status</label>
                <select
                    className="input text-sm py-1"
                    value={statusFilter}
                    onChange={(e) => onStatusChange(e.target.value)}
                >
                    <option value="">All Statuses</option>
                    <option value="pending">Pending</option>
                    <option value="resolved">Resolved</option>
                </select>
            </div>

            <div className="space-y-2">
                <label className="text-xs font-medium text-muted uppercase">
                    Min Match Score: {minScore}
                    <InfoHint term="match_score" label="Match score" />
                </label>
                <input
                    type="range"
                    min="0"
                    max="100"
                    step="5"
                    value={minScore}
                    onChange={(e) => onMinScoreChange(parseInt(e.target.value))}
                    className="w-full h-2 bg-[var(--border)] rounded-lg appearance-none cursor-pointer accent-[var(--accent)]"
                />
            </div>
        </div>
    );
}
