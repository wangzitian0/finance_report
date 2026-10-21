import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";

import AuditPage from "@/app/(main)/audit/page";

describe("Audit hub (EPIC-022 AC22.21.3)", () => {
    // AC-ledger.fe-processing.5
    it("AC15.7.6 aggregates the verify-on-demand machinery (incl. Processing) as deep-linking cards", () => {
        render(<AuditPage />);

        expect(screen.getByRole("heading", { name: "Audit" })).toBeInTheDocument();

        const links = [
            { name: /Trust/, href: "/confidence" },
            { name: /Reconciliation/, href: "/reconciliation" },
            { name: /Journal/, href: "/journal" },
            { name: /Statements/, href: "/upload" },
            { name: /Processing/, href: "/processing" },
        ];
        for (const { name, href } of links) {
            expect(screen.getByRole("link", { name }).closest("a")).toHaveAttribute("href", href);
        }
    });

    it("renders the unified Needs Confirmation quick-triage bar in plain language", () => {
        render(<AuditPage />);

        const bar = screen.getByTestId("audit-needs-confirmation-bar");
        expect(within(bar).getByRole("heading", { name: "Needs Confirmation" })).toBeInTheDocument();

        expect(within(bar).getByRole("link", { name: "Low-confidence items" })).toHaveAttribute(
            "href",
            "/attention",
        );
        expect(within(bar).getByRole("link", { name: "Unmatched bank lines" })).toHaveAttribute(
            "href",
            "/reconciliation/unmatched",
        );
        expect(within(bar).getByRole("link", { name: "Uploaded statements" })).toHaveAttribute(
            "href",
            "/upload",
        );

        expect(screen.queryByText(/TraceRecord/i)).not.toBeInTheDocument();
        expect(screen.queryByText(/Stage2/i)).not.toBeInTheDocument();
        expect(screen.queryByText(/Layer-2/i)).not.toBeInTheDocument();
    });
});
