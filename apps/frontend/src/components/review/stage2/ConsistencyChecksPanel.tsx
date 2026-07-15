import { InfoHint } from "@/components/ui/InfoHint";
import { formatDateTimeDisplay } from "@/lib/date";
import { checkSeverityColor, checkTypeLabel } from "@/lib/statusLabels";
import type { ConsistencyCheck } from "@/lib/types";

interface ConsistencyChecksPanelProps {
    checks: ConsistencyCheck[];
    onResolve: (check: ConsistencyCheck) => void;
}

export function ConsistencyChecksPanel({ checks, onResolve }: ConsistencyChecksPanelProps) {
    return (
        <div className="card">
            <div className="card-header flex items-center justify-between">
                <h3 className="text-sm font-medium">
                    Consistency Checks
                    <InfoHint term="consistency_check" label="Consistency check" />
                </h3>
                <span className="text-xs text-muted">{checks.length} total</span>
            </div>

            {checks.length === 0 ? (
                <div className="p-8 text-center text-muted">No pending checks</div>
            ) : (
                <div className="divide-y divide-[var(--border)]">
                    {checks.map((check) => (
                        <div key={check.id} className="p-4 flex items-start justify-between gap-4">
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 mb-1">
                                    <span className={`font-medium text-xs ${checkSeverityColor(check.severity)}`}>
                                        {check.severity.toUpperCase()}
                                    </span>
                                    <span className="badge badge-muted text-[10px]">{checkTypeLabel(check.check_type)}</span>
                                </div>
                                <p className="text-sm text-muted truncate">
                                    {(check.details.message as string | undefined) || JSON.stringify(check.details)}
                                </p>
                                <p className="text-xs text-muted mt-1">
                                    {formatDateTimeDisplay(check.created_at)}
                                </p>
                            </div>
                            <button
                                type="button"
                                onClick={() => onResolve(check)}
                                className="btn-secondary text-sm"
                            >
                                Resolve
                            </button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
