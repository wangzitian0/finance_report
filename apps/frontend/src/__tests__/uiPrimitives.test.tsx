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
} from "@/components/ui"

describe("UI primitives", () => {
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

  it("AC16.28.2 AC16.28.4 requires icon-only actions to expose an accessible label", () => {
    render(<IconButton icon={Pencil} label="Edit account" />)

    const button = screen.getByRole("button", { name: "Edit account" })
    expect(button).toHaveAttribute("aria-label", "Edit account")
    expect(button).toHaveAttribute("title", "Edit account")
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
})
