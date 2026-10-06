import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownMessage } from "@/components/chat/MarkdownMessage";

describe("MarkdownMessage", () => {
  it("renders plain text paragraphs", () => {
    render(<MarkdownMessage content="Hello financial world" />);
    expect(screen.getByText("Hello financial world")).toBeInTheDocument();
  });

  it("renders bold text and code snippets", () => {
    const { container } = render(<MarkdownMessage content="Total is **$5,000.00** with code `SGD`" />);
    expect(screen.getByText("$5,000.00")).toBeInTheDocument();
    expect(screen.getByText("SGD")).toBeInTheDocument();
    expect(container.querySelector("strong")).toBeInTheDocument();
    expect(container.querySelector("code")).toBeInTheDocument();
  });

  it("renders headings", () => {
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

  it("renders markdown tables properly", () => {
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

  it("renders unordered and ordered lists", () => {
    const listMarkdown = `
- Item A
- Item B

1. First step
2. Second step
`;
    render(<MarkdownMessage content={listMarkdown} />);
    expect(screen.getByText("Item A")).toBeInTheDocument();
    expect(screen.getByText("Item B")).toBeInTheDocument();
    expect(screen.getByText("First step")).toBeInTheDocument();
    expect(screen.getByText("Second step")).toBeInTheDocument();
  });

  it("renders blockquotes", () => {
    const quoteMarkdown = "> Important financial note: review quarterly.";
    const { container } = render(<MarkdownMessage content={quoteMarkdown} />);
    expect(container.querySelector("blockquote")).toBeInTheDocument();
    expect(screen.getByText("Important financial note: review quarterly.")).toBeInTheDocument();
  });
});
