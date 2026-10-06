// AC-advisor.fe-chat.7
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownMessage } from "@/components/chat/MarkdownMessage";

describe("AC-advisor.fe-chat.7 MarkdownMessage", () => {
  it("renders null when content is empty or falsy", () => {
    const { container } = render(<MarkdownMessage content="" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders plain text paragraphs and custom className", () => {
    const { container } = render(
      <MarkdownMessage content="Hello financial world" className="custom-style" />
    );
    expect(screen.getByText("Hello financial world")).toBeInTheDocument();
    expect(container.firstChild).toHaveClass("custom-style");
  });

  it("renders bold, italic, and inline code formatting", () => {
    const { container } = render(
      <MarkdownMessage content="Total is **$5,000.00** with code `SGD` and *estimated* note" />
    );
    expect(screen.getByText("$5,000.00")).toBeInTheDocument();
    expect(screen.getByText("SGD")).toBeInTheDocument();
    expect(screen.getByText("estimated")).toBeInTheDocument();
    expect(container.querySelector("strong")).toBeInTheDocument();
    expect(container.querySelector("code")).toBeInTheDocument();
    expect(container.querySelector("em")).toBeInTheDocument();
  });

  it("renders headings of various levels", () => {
    render(
      <MarkdownMessage
        content={`# Title 1
## Section 2
### Sub 3`}
      />
    );
    expect(screen.getByRole("heading", { level: 2, name: "Title 1" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Section 2" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 4, name: "Sub 3" })).toBeInTheDocument();
  });

  it("renders markdown tables properly with headers and body rows", () => {
    const tableMarkdown = `
| Asset Class | Value | Ratio |
| :--- | :--- | :--- |
| Cash | $10,000 | 25% |
| Equity | $30,000 | 75% |
`;
    const { container } = render(<MarkdownMessage content={tableMarkdown} />);
    expect(container.querySelector("table")).toBeInTheDocument();
    expect(screen.getByText("Asset Class")).toBeInTheDocument();
    expect(screen.getByText("Equity")).toBeInTheDocument();
    expect(screen.getByText("$30,000")).toBeInTheDocument();
  });

  it("falls back to paragraph when lines contain pipes without a valid table separator", () => {
    const invalidTable = `
| Pipe text without separator
| Another line with pipe
`;
    const { container } = render(<MarkdownMessage content={invalidTable} />);
    expect(container.querySelector("table")).toBeNull();
    expect(screen.getByText(/Pipe text without separator/)).toBeInTheDocument();
  });

  it("renders unordered lists with dash and asterisk markers", () => {
    const listMarkdown = `
- Dash item 1
- Dash item 2
* Asterisk item 3
`;
    render(<MarkdownMessage content={listMarkdown} />);
    expect(screen.getByText("Dash item 1")).toBeInTheDocument();
    expect(screen.getByText("Dash item 2")).toBeInTheDocument();
    expect(screen.getByText("Asterisk item 3")).toBeInTheDocument();
  });

  it("renders ordered lists with numeric prefixes", () => {
    const listMarkdown = `
1. First step
2. Second step
`;
    render(<MarkdownMessage content={listMarkdown} />);
    expect(screen.getByText("First step")).toBeInTheDocument();
    expect(screen.getByText("Second step")).toBeInTheDocument();
  });

  it("renders single and multiline blockquotes", () => {
    const quoteMarkdown = `
> Important financial note: review quarterly.
> Follow up on anomalies.
`;
    const { container } = render(<MarkdownMessage content={quoteMarkdown} />);
    expect(container.querySelector("blockquote")).toBeInTheDocument();
    expect(
      screen.getByText(/Important financial note: review quarterly\.\s*Follow up on anomalies\./)
    ).toBeInTheDocument();
  });

  it("handles blank lines between blocks gracefully", () => {
    const content = `
Paragraph 1

Paragraph 2
`;
    render(<MarkdownMessage content={content} />);
    expect(screen.getByText("Paragraph 1")).toBeInTheDocument();
    expect(screen.getByText("Paragraph 2")).toBeInTheDocument();
  });
});
