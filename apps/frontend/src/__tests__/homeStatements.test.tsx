import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { ThreeStatementNav } from "@/components/home/ThreeStatementNav";

describe("Home three-statement entry (EPIC-022 AC22.21.6)", () => {
    it("deep-links each of the three statements to its full report", () => {
        render(<ThreeStatementNav />);

        expect(screen.getByRole("navigation", { name: "Financial statements" })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /Balance Sheet/ })).toHaveAttribute(
            "href",
            "/reports/balance-sheet",
        );
        expect(screen.getByRole("link", { name: /Income/ })).toHaveAttribute(
            "href",
            "/reports/income-statement",
        );
        expect(screen.getByRole("link", { name: /Cash Flow/ })).toHaveAttribute(
            "href",
            "/reports/cash-flow",
        );
    });
});
