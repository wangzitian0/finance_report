import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { InfoHint, GLOSSARY } from "@/components/ui/InfoHint";

describe("InfoHint (EPIC-022 AC22.5.5)", () => {
    it("AC22.5.5 exposes the plain-language glossary text to assistive tech", () => {
        render(<InfoHint term="transfer_pair" label="Transfer pair" />);
        const hint = screen.getByRole("img");
        expect(hint).toHaveAttribute("title", GLOSSARY.transfer_pair);
        expect(hint.getAttribute("aria-label")).toContain(GLOSSARY.transfer_pair);
        expect(hint.getAttribute("aria-label")).toContain("Transfer pair");
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
});
