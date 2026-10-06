import React from "react";

interface MarkdownMessageProps {
  content: string;
  className?: string;
}

/**
 * Parses inline formatting: **bold**, *italic*, and `code`
 */
function renderInline(text: string): React.ReactNode {
  // Regex to match **bold**, *italic*, and `code`
  const parts: React.ReactNode[] = [];
  const regex = /(\*\*.*?\*\*|\*.*?\*|`.*?`)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  let keyIndex = 0;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.substring(lastIndex, match.index));
    }
    const token = match[0];
    if (token.startsWith("**") && token.endsWith("**")) {
      parts.push(
        <strong key={`b-${keyIndex++}`} className="font-semibold text-[var(--foreground)]">
          {token.slice(2, -2)}
        </strong>
      );
    } else if (token.startsWith("`") && token.endsWith("`")) {
      parts.push(
        <code
          key={`c-${keyIndex++}`}
          className="rounded bg-[var(--background)] px-1.5 py-0.5 font-mono text-xs border border-[var(--border)] text-[var(--accent)]"
        >
          {token.slice(1, -1)}
        </code>
      );
    } else if (token.startsWith("*") && token.endsWith("*")) {
      parts.push(
        <em key={`i-${keyIndex++}`} className="italic">
          {token.slice(1, -1)}
        </em>
      );
    }
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex));
  }

  return parts.length > 0 ? parts : text;
}

/**
 * Checks if a block of lines is a markdown table
 */
function isTableBlock(lines: string[]): boolean {
  if (lines.length < 2) return false;
  const hasPipes = lines.every((line) => line.trim().startsWith("|") || line.includes("|"));
  const hasSeparator = lines.some((line) => /^\s*\|?(\s*:?-+:?\s*\|)+\s*$/.test(line));
  return hasPipes && hasSeparator;
}

/**
 * Renders a Markdown table cleanly with accessible HTML and tailwind styles
 */
function renderTable(lines: string[], keyPrefix: string): React.ReactNode {
  const cleanLines = lines.map((l) => l.trim()).filter(Boolean);
  if (cleanLines.length < 2) return null;

  const headerLine = cleanLines[0];
  const separatorLineIndex = cleanLines.findIndex((l) =>
    /^\s*\|?(\s*:?-+:?\s*\|)+\s*$/.test(l)
  );

  if (separatorLineIndex === -1) return null;

  const parseRow = (line: string) => {
    let raw = line;
    if (raw.startsWith("|")) raw = raw.slice(1);
    if (raw.endsWith("|")) raw = raw.slice(0, -1);
    return raw.split("|").map((cell) => cell.trim());
  };

  const headers = parseRow(headerLine);
  const bodyRows = cleanLines
    .slice(separatorLineIndex + 1)
    .filter((l) => l.includes("|"))
    .map(parseRow);

  return (
    <div
      key={keyPrefix}
      className="my-3 overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--background)] shadow-xs"
    >
      <table className="min-w-full divide-y divide-[var(--border)] text-left text-xs">
        <thead className="bg-[var(--background-muted)] font-medium text-[var(--foreground)]">
          <tr>
            {headers.map((h, i) => (
              <th key={i} className="px-3 py-2">
                {renderInline(h)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--border)]/60">
          {bodyRows.map((row, rIdx) => (
            <tr
              key={rIdx}
              className="hover:bg-[var(--background-muted)]/40 transition-colors"
            >
              {row.map((cell, cIdx) => (
                <td key={cIdx} className="px-3 py-2 font-mono">
                  {renderInline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Zero-dependency, safe Markdown message formatter for financial chat responses.
 * Handles headings, tables, bullet/numbered lists, inline bold/code, and paragraphs.
 */
export function MarkdownMessage({ content, className = "" }: MarkdownMessageProps) {
  if (!content) return null;

  const lines = content.split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i++;
      continue;
    }

    // Check for Table
    if (trimmed.startsWith("|") || (trimmed.includes("|") && i + 1 < lines.length && lines[i + 1].includes("---"))) {
      const tableLines: string[] = [];
      while (i < lines.length && (lines[i].includes("|") || lines[i].trim().startsWith("|"))) {
        tableLines.push(lines[i]);
        i++;
      }
      if (isTableBlock(tableLines)) {
        blocks.push(renderTable(tableLines, `table-${blocks.length}`));
        continue;
      } else {
        // Fallback if not a real table
        blocks.push(
          <p key={`p-${blocks.length}`} className="my-1.5 text-sm leading-relaxed">
            {renderInline(tableLines.join("\n"))}
          </p>
        );
        continue;
      }
    }

    // Headings
    if (trimmed.startsWith("### ")) {
      blocks.push(
        <h4
          key={`h4-${blocks.length}`}
          className="mt-3 mb-1.5 text-sm font-semibold text-[var(--foreground)]"
        >
          {renderInline(trimmed.slice(4))}
        </h4>
      );
      i++;
      continue;
    }
    if (trimmed.startsWith("## ")) {
      blocks.push(
        <h3
          key={`h3-${blocks.length}`}
          className="mt-3.5 mb-1.5 text-base font-semibold text-[var(--foreground)]"
        >
          {renderInline(trimmed.slice(3))}
        </h3>
      );
      i++;
      continue;
    }
    if (trimmed.startsWith("# ")) {
      blocks.push(
        <h2
          key={`h2-${blocks.length}`}
          className="mt-4 mb-2 text-lg font-bold text-[var(--foreground)]"
        >
          {renderInline(trimmed.slice(2))}
        </h2>
      );
      i++;
      continue;
    }

    // Unordered List
    if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      const listItems: string[] = [];
      while (i < lines.length && (lines[i].trim().startsWith("- ") || lines[i].trim().startsWith("* "))) {
        listItems.push(lines[i].trim().slice(2));
        i++;
      }
      blocks.push(
        <ul key={`ul-${blocks.length}`} className="my-2 list-disc pl-5 space-y-1 text-sm">
          {listItems.map((item, idx) => (
            <li key={idx} className="leading-relaxed">
              {renderInline(item)}
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // Ordered List
    if (/^\d+\.\s/.test(trimmed)) {
      const listItems: string[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i].trim())) {
        listItems.push(lines[i].trim().replace(/^\d+\.\s/, ""));
        i++;
      }
      blocks.push(
        <ol key={`ol-${blocks.length}`} className="my-2 list-decimal pl-5 space-y-1 text-sm">
          {listItems.map((item, idx) => (
            <li key={idx} className="leading-relaxed">
              {renderInline(item)}
            </li>
          ))}
        </ol>
      );
      continue;
    }

    // Blockquote
    if (trimmed.startsWith("> ")) {
      const quoteLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("> ")) {
        quoteLines.push(lines[i].trim().slice(2));
        i++;
      }
      blocks.push(
        <blockquote
          key={`quote-${blocks.length}`}
          className="my-2 border-l-2 border-[var(--accent)] pl-3 italic text-muted text-sm"
        >
          {renderInline(quoteLines.join(" "))}
        </blockquote>
      );
      continue;
    }

    // Standard Paragraph
    blocks.push(
      <p key={`p-${blocks.length}`} className="my-1.5 text-sm leading-relaxed">
        {renderInline(trimmed)}
      </p>
    );
    i++;
  }

  return <div className={`space-y-1 text-[var(--foreground)] ${className}`}>{blocks}</div>;
}
