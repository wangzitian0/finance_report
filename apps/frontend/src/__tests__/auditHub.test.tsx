import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import AuditPage from "@/app/(main)/audit/page";

describe("Audit hub (EPIC-022 AC22.21.3)", () => {
    it("aggregates the verify-on-demand machinery as deep-linking cards", () => {
        render(<AuditPage />);

        expect(screen.getByRole("heading", { name: "Audit" })).toBeInTheDocument();

        const links = [
            { name: /Trust/, href: "/confidence" },
            { name: /Reconciliation/, href: "/reconciliation" },
            { name: /Journal/, href: "/journal" },
            { name: /Processing/, href: "/processing" },
        ];
        for (const { name, href } of links) {
            expect(screen.getByRole("link", { name }).closest("a")).toHaveAttribute("href", href);
        }
    });
});
