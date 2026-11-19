import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { MarkdownMessage } from "@/components/chat/MarkdownMessage";
const S = screen, E = expect;
it("AC-advisor.fe-chat.7 MarkdownMessage", () => {
E(render(<MarkdownMessage content="" />).container.firstChild).toBeNull();
const { container, rerender } = render(<MarkdownMessage content="Hi **$5** `SGD` *e*" className="cs" />);
E(container.firstChild).toHaveClass("cs");
for (const [sel, t] of [["strong", "$5"], ["code", "SGD"], ["em", "e"]] as const) { E(container.querySelector(sel)).toBeInTheDocument(); E(S.getByText(t)).toBeInTheDocument(); }
rerender(<MarkdownMessage content={"# T1\n## S2\n### S3\n\n| A | B |\n| :--- | :--- |\n| Cash | $10 |\n\n- D1\n* S1\n1. O1\n2. O2\n\n> Q1\n> Q2\n\nP1\n\nP2"} />);
for (const [l, n] of [[2, "T1"], [3, "S2"], [4, "S3"]] as const) E(S.getByRole("heading", { level: l, name: n })).toBeInTheDocument();
E(container.querySelector("table")).toBeInTheDocument();
E(container.querySelector("blockquote")).toBeInTheDocument();
for (const s of ["Cash", "$10", "D1", "S1", "O1", "O2", /Q1\s*Q2/, "P1", "P2"]) E(S.getByText(s)).toBeInTheDocument();
rerender(<MarkdownMessage content={"| No sep\n| Line 2"} />);
E(container.querySelector("table")).toBeNull();
E(S.getByText(/No sep/)).toBeInTheDocument();
});
