import { formatPercentFromRatioValue } from "@/lib/audit/ratio/format";
import type { CorrectionLoopReplayResponse } from "@/lib/types";

export interface ReplaySummary {
  reduced: boolean;
  before: string;
  after: string;
  hasHoldout: boolean;
}

export function summarizeReplay(replay: CorrectionLoopReplayResponse): ReplaySummary {
  return {
    reduced: replay.reduced,
    before: formatPercentFromRatioValue(replay.proportion_before, { dp: 1 }),
    after: formatPercentFromRatioValue(replay.proportion_after, { dp: 1 }),
    hasHoldout: replay.holdout_size > 0,
  };
}
