import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import AddSheet from "@/components/shell/AddSheet";

vi.mock("@/components/statements/StatementUploader", () => ({
    default: ({ kind, onUploadComplete }: { kind?: string; onUploadComplete?: () => void }) => (
        <button data-testid="uploader" onClick={() => onUploadComplete?.()}>
            UploaderMock-{kind}
        </button>
    ),
}));

vi.mock("@/components/assets/GuidedEvidenceForm", () => ({
    default: () => <div data-testid="evidence-form">EvidenceMock</div>,
}));

describe("AddSheet (EPIC-022 AC22.21.2)", () => {
    it("renders nothing when closed", () => {
        render(<AddSheet isOpen={false} onClose={() => {}} />);
        expect(screen.queryByText("Upload statement")).toBeNull();
    });

    it("offers the two ways to add and reveals the statement uploader", () => {
        render(<AddSheet isOpen onClose={() => {}} />);
        expect(screen.getByText("Upload statement")).toBeInTheDocument();
        expect(screen.getByText("Manual entry")).toBeInTheDocument();

        fireEvent.click(screen.getByText("Upload statement"));
        expect(screen.getByTestId("uploader")).toHaveTextContent("UploaderMock-all");
    });

    it("reveals the guided evidence form for manual entry", () => {
        render(<AddSheet isOpen onClose={() => {}} />);
        fireEvent.click(screen.getByText("Manual entry"));
        expect(screen.getByTestId("evidence-form")).toBeInTheDocument();
    });

    it("fires onUploadComplete and closes after a successful upload", () => {
        const onClose = vi.fn();
        const onUploadComplete = vi.fn();
        render(<AddSheet isOpen onClose={onClose} onUploadComplete={onUploadComplete} />);

        fireEvent.click(screen.getByText("Upload statement"));
        fireEvent.click(screen.getByTestId("uploader"));

        expect(onUploadComplete).toHaveBeenCalledTimes(1);
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("closes via the sheet's close control", () => {
        const onClose = vi.fn();
        render(<AddSheet isOpen onClose={onClose} />);
        fireEvent.click(screen.getByRole("button", { name: /close panel/i }));
        expect(onClose).toHaveBeenCalledTimes(1);
    });
});
