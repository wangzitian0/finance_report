// AC-extraction.human-source-review.1: PDF preview pane resilience and download fallback
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PdfPreviewPane } from "@/components/review/PdfPreviewPane";
import { apiOperationDownload } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiOperationDownload: vi.fn(),
}));

describe("PdfPreviewPane (BUG-04 resilience & fallback)", () => {
  const mockedApiDownload = vi.mocked(apiOperationDownload);

  beforeEach(() => {
    mockedApiDownload.mockReset();
    global.URL.createObjectURL = vi.fn(() => "blob:http://localhost/mock-pdf");
    global.URL.revokeObjectURL = vi.fn();
  });

  it("renders download link and open in new tab when PDF is loaded", async () => {
    mockedApiDownload.mockResolvedValue({
      blob: new Blob(["mock content"], { type: "application/pdf" }),
      filename: "statement.pdf",
    });

    render(<PdfPreviewPane statementId="stmt-123" hasDocument={true} />);

    await waitFor(() => {
      expect(screen.getByTestId("pdf-download-link")).toBeInTheDocument();
    });

    expect(screen.getByText("Open in new tab")).toBeInTheDocument();
    const downloadLink = screen.getByTestId("pdf-download-link");
    expect(downloadLink).toHaveAttribute("href", "blob:http://localhost/mock-pdf");
    expect(downloadLink).toHaveAttribute("download", "statement.pdf");
  });

  it("renders fallback UI with retry / download options when loading fails", async () => {
    mockedApiDownload.mockRejectedValue(new Error("Network failure"));

    render(<PdfPreviewPane statementId="stmt-123" hasDocument={true} />);

    await waitFor(() => {
      expect(screen.getByText(/PDF preview could not be loaded/i)).toBeInTheDocument();
    });

    expect(screen.getByTestId("pdf-fallback-container")).toBeInTheDocument();
  });
});
