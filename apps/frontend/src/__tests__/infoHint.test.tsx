import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { InfoHint, GLOSSARY } from "@/components/ui/InfoHint";

describe("InfoHint (EPIC-022 AC22.5.5)", () => {
    it("AC22.5.5 exposes the plain-language glossary text to assistive tech", () => {
        render(<InfoHint term="transfer_pair" label="Transfer pair" />);
        const hint = screen.getByRole("img");
        expect(hint.getAttribute("aria-label")).toContain(GLOSSARY.transfer_pair);
        expect(hint.getAttribute("aria-label")).toContain("Transfer pair");
        // The explanation is also rendered as a visible tooltip (shown on hover
        // and keyboard focus), not delivered solely via a title attribute.
        expect(screen.getByRole("tooltip")).toHaveTextContent(GLOSSARY.transfer_pair);
    });

    it("AC22.5.5 is keyboard focusable so the hint is not mouse-only", () => {
        render(<InfoHint term="match_score" />);
        expect(screen.getByRole("img")).toHaveAttribute("tabindex", "0");
    });

    it("AC22.5.5 covers the core jargon terms", () => {
        for (const term of ["drift", "needs_review", "anomaly", "duplicate", "consistency_check"] as const) {
            expect(GLOSSARY[term]).toBeTruthy();
        }
    });

    it("AC22.9.2 exposes a single reconciliation-coverage term for the unified label", () => {
        // Home and Reports both render "Reconciliation coverage" backed by this
        // one glossary entry, replacing the old divergent "Data health" /
        // "Statistics Accuracy" wording.
        expect(GLOSSARY.reconciliation_coverage).toBeTruthy();
        render(<InfoHint term="reconciliation_coverage" label="Reconciliation coverage" />);
        expect(screen.getByRole("tooltip")).toHaveTextContent(GLOSSARY.reconciliation_coverage);
    });
});
