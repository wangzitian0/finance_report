import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import AddSheet from "@/components/shell/AddSheet";

vi.mock("@/components/statements/StatementUploader", () => ({
    default: ({ kind }: { kind?: string }) => <div data-testid="uploader">UploaderMock-{kind}</div>,
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
        expect(screen.getByTestId("uploader")).toHaveTextContent("UploaderMock-statement");
    });

    it("reveals the guided evidence form for manual entry", () => {
        render(<AddSheet isOpen onClose={() => {}} />);
        fireEvent.click(screen.getByText("Manual entry"));
        expect(screen.getByTestId("evidence-form")).toBeInTheDocument();
    });
});
