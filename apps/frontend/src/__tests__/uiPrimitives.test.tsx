import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { Pencil } from "lucide-react";
import { expect, it } from "vitest";
import { Alert, Badge, Button, EmptyState, IconButton, LoadingState, PageHeader, SkeletonBlock } from "@/components/ui";
const S = screen, E = expect;
it("AC16.28.1 AC16.28.2 AC16.28.4 AC16.30.1 AC16.30.4 AC22.12.6 UI primitives", () => {
const r1 = render(<div><Button variant="primary">Create</Button><Button variant="secondary">Cancel</Button><Button variant="ghost">Quiet</Button><Button variant="danger">Delete</Button><Badge variant="success">Posted</Badge><IconButton icon={Pencil} label="Edit" {...({ "aria-label": "Wrong" } as Record<string, string>)} /><PageHeader title="Accounts" description="Manage" actions={<Button>Add</Button>} /><Alert variant="error">Failed</Alert><EmptyState title="Empty" action={<Button>First</Button>} /><LoadingState label="Loading" /></div>);
for (const [n, c] of [["Create", "btn-primary"], ["Cancel", "btn-secondary"], ["Quiet", "btn-ghost"], ["Delete", "btn-danger"]] as const) E(S.getByRole("button", { name: n })).toHaveClass(c);
E(S.getByText("Posted")).toHaveClass("badge-success");
const icon = S.getByRole("button", { name: "Edit" });
E(icon).toHaveAttribute("aria-label", "Edit");
E(icon).toHaveAttribute("title", "Edit");
E(S.queryByRole("button", { name: "Wrong" })).toBeNull();
E(S.getByRole("heading", { name: "Accounts" })).toBeInTheDocument();
E(S.getByText("Manage")).toBeInTheDocument();
E(S.getByRole("alert")).toHaveTextContent("Failed");
E(S.getByText("Empty")).toBeInTheDocument();
E(S.getByRole("status", { name: "Loading" })).toBeInTheDocument();
r1.unmount();
const { container } = render(<div><SkeletonBlock label="Metric" className="h-6 w-24" /><SkeletonBlock className="h-4 w-full" /></div>);
E(S.getByRole("status", { name: "Metric" })).toHaveAttribute("aria-busy", "true");
E(S.getAllByRole("status")).toHaveLength(1);
E(container.querySelectorAll("[data-testid='skeleton-block'].animate-pulse.bg-surface-muted")).toHaveLength(2);
E(container.querySelector(".animate-spin")).toBeNull();
});
// AC-meta.fe-app-shell.22 AC-meta.fe-app-shell.23 AC-meta.fe-app-shell.25 AC-meta.fe-app-shell.30 AC-meta.fe-ia-nav.17
