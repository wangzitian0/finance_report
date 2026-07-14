import "@testing-library/jest-dom/vitest"
import { render, screen } from "@testing-library/react"
import { Pencil } from "lucide-react"
import { describe, expect, it } from "vitest"

import {
  Alert,
  Badge,
  Button,
  EmptyState,
  IconButton,
  LoadingState,
  PageHeader,
  SkeletonBlock,
  TableSkeleton,
} from "@/components/ui"

describe("UI primitives", () => {
  // AC-meta.fe-app-shell.22 / AC-meta.fe-app-shell.25
  it("AC16.28.1 AC16.28.4 renders button and badge variants through shared primitives", () => {
    render(
      <div>
        <Button variant="primary">Create</Button>
        <Button variant="secondary">Cancel</Button>
        <Button variant="ghost">Quiet</Button>
        <Button variant="danger">Delete</Button>
        <Badge variant="success">Posted</Badge>
      </div>,
    )

    expect(screen.getByRole("button", { name: "Create" })).toHaveClass("btn-primary")
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveClass("btn-secondary")
    expect(screen.getByRole("button", { name: "Quiet" })).toHaveClass("btn-ghost")
    expect(screen.getByRole("button", { name: "Delete" })).toHaveClass("btn-danger")
    expect(screen.getByText("Posted")).toHaveClass("badge-success")
  })

  // AC-meta.fe-app-shell.23
  it("AC16.28.2 AC16.28.4 requires icon-only actions to expose an accessible label", () => {
    render(<IconButton icon={Pencil} label="Edit account" />)

    const button = screen.getByRole("button", { name: "Edit account" })
    expect(button).toHaveAttribute("aria-label", "Edit account")
    expect(button).toHaveAttribute("title", "Edit account")
  })

  // AC-meta.fe-app-shell.30
  it("AC16.30.1 AC16.30.4 keeps IconButton label authoritative over passthrough props", () => {
    render(
      <IconButton
        icon={Pencil}
        label="Edit account"
        {...({ "aria-label": "Wrong label" } as Record<string, string>)}
      />,
    )

    const button = screen.getByRole("button", { name: "Edit account" })
    expect(button).toHaveAttribute("aria-label", "Edit account")
    expect(screen.queryByRole("button", { name: "Wrong label" })).not.toBeInTheDocument()
  })

  it("AC16.28.1 AC16.28.4 renders shared alert, empty, loading, and page header states", () => {
    render(
      <div>
        <PageHeader title="Accounts" description="Manage chart of accounts" actions={<Button>Add</Button>} />
        <Alert variant="error">Failed to load</Alert>
        <EmptyState title="No accounts yet" action={<Button>Create First Account</Button>} />
        <LoadingState label="Loading accounts" />
      </div>,
    )

    expect(screen.getByRole("heading", { name: "Accounts" })).toBeInTheDocument()
    expect(screen.getByText("Manage chart of accounts")).toBeInTheDocument()
    expect(screen.getByRole("alert")).toHaveTextContent("Failed to load")
    expect(screen.getByText("No accounts yet")).toBeInTheDocument()
    expect(screen.getByRole("status", { name: "Loading accounts" })).toBeInTheDocument()
  })

  // AC-meta.fe-ia-nav.17
  it("AC22.12.6 renders token-backed skeleton primitives without spinner affordances", () => {
    const { container } = render(
      <div>
        <SkeletonBlock label="Loading metric" className="h-6 w-24" />
        <TableSkeleton label="Loading report rows" rows={2} columns={3} />
      </div>,
    )

    expect(screen.getByRole("status", { name: "Loading metric" })).toHaveAttribute("aria-busy", "true")
    expect(screen.getByRole("status", { name: "Loading report rows" })).toHaveAttribute("aria-busy", "true")
    expect(container.querySelectorAll("[data-testid='skeleton-block']").length).toBeGreaterThanOrEqual(7)
    expect(container.querySelector(".animate-spin")).toBeNull()
  })
})
