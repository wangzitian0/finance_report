import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { FlowStepBanner } from "@/components/workflow/FlowStepBanner";

vi.mock("next/link", () => ({
    __esModule: true,
    default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
        <a href={href} {...rest}>
            {children}
        </a>
    ),
}));

describe("FlowStepBanner (EPIC-022 AC22.5.1)", () => {
    // AC-meta.fe-ia-nav.10
    it("AC22.5.1 renders the Upload -> Review & approve -> Reports path", () => {
        render(<FlowStepBanner current="upload" />);
        expect(screen.getByRole("link", { name: /Upload/ })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /Review & approve/ })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /Reports/ })).toBeInTheDocument();
    });

    it("AC22.5.1 marks the current step with aria-current", () => {
        render(<FlowStepBanner current="review" />);
        const current = screen.getByRole("link", { name: /Review & approve/ });
        expect(current).toHaveAttribute("aria-current", "step");
        expect(screen.getByRole("link", { name: /Upload/ })).not.toHaveAttribute("aria-current");
    });

    it("AC22.5.1 shows a next-step hint for the current step", () => {
        render(<FlowStepBanner current="upload" />);
        expect(screen.getByText(/Next: once we parse your statement/i)).toBeInTheDocument();
    });

    it("AC22.12.5 uses semantic icons instead of unicode status glyphs", () => {
        const { container } = render(<FlowStepBanner current="reports" />);

        expect(container.textContent).not.toContain("✓");
        expect(container.textContent).not.toContain("→");
        expect(screen.getByRole("link", { name: /Upload/ })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /Review & approve/ })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: /Reports/ })).toHaveAttribute("aria-current", "step");
    });
});
