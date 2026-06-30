import type { ReactNode } from "react";
import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { AuditBackLink } from "@/components/audit/AuditBackLink";

const navigationState = vi.hoisted(() => ({
    searchParams: new URLSearchParams(),
}));

vi.mock("next/link", () => ({
    __esModule: true,
    default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
        <a href={href} {...rest}>
            {children}
        </a>
    ),
}));

vi.mock("next/navigation", () => ({
    useSearchParams: () => navigationState.searchParams,
}));

describe("Audit hub back-link (EPIC-022 AC22.21.3)", () => {
    beforeEach(() => {
        navigationState.searchParams = new URLSearchParams();
    });

    it("returns to the Audit hub by default", () => {
        render(<AuditBackLink />);
        expect(screen.getByRole("link", { name: /Back to Audit/i })).toHaveAttribute("href", "/audit");
    });

    it("returns attention-origin users to the attention queue instead", () => {
        navigationState.searchParams = new URLSearchParams("from=attention");
        render(<AuditBackLink />);
        expect(screen.getByRole("link", { name: /Back to Attention queue/i })).toHaveAttribute(
            "href",
            "/attention",
        );
    });
});
