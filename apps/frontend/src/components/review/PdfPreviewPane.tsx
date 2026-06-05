"use client";

interface PdfPreviewPaneProps {
    pdfUrl: string | null;
}

export function PdfPreviewPane({ pdfUrl }: PdfPreviewPaneProps) {
    return (
        <div className="card flex flex-col min-h-0 h-full">
            <div className="card-header">
                <h3 className="text-sm font-medium">PDF Preview</h3>
            </div>
            <div className="flex-1 p-4 min-h-0">
                {pdfUrl ? (
                    <iframe 
                        src={pdfUrl} 
                        className="w-full h-full rounded border" 
                        title="Statement PDF preview"
                        sandbox="allow-same-origin"
                        referrerPolicy="no-referrer"
                    >
                        <p>PDF preview not available. Use the data table below to review statement content.</p>
                    </iframe>
                ) : (
                    <div className="w-full h-full flex items-center justify-center text-muted">
                        PDF preview not available
                    </div>
                )}
            </div>
        </div>
    );
}
