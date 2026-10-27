import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import type { DataProvenance } from "@/lib/types";

export function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

const buttonClasses: Record<ButtonVariant, string> = {
  primary: "btn-primary",
  secondary: "btn-secondary",
  ghost: "btn-ghost",
  danger: "btn-danger",
};

export function Button({
  variant = "primary",
  className,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(buttonClasses[variant], "disabled:cursor-not-allowed", className)}
      {...props}
    />
  );
}

interface IconButtonProps extends Omit<ButtonProps, "aria-label" | "children"> {
  icon: LucideIcon;
  label: string;
}

export function IconButton({
  icon: Icon,
  label,
  variant = "ghost",
  className,
  title,
  ...props
}: IconButtonProps) {
  return (
    <Button
      variant={variant}
      className={cx("inline-flex h-11 w-11 items-center justify-center p-2", className)}
      {...props}
      aria-label={label}
      title={title ?? label}
    >
      <Icon className="h-5 w-5" aria-hidden="true" />
    </Button>
  );
}

export type BadgeVariant = "primary" | "success" | "warning" | "error" | "info" | "muted";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

const badgeClasses: Record<BadgeVariant, string> = {
  primary: "badge-primary",
  success: "badge-success",
  warning: "badge-warning",
  error: "badge-error",
  info: "badge-info",
  muted: "badge-muted",
};

export function Badge({ variant = "muted", className, ...props }: BadgeProps) {
  return <span className={cx("badge", badgeClasses[variant], className)} {...props} />;
}

interface StatusBadgeProps extends HTMLAttributes<HTMLSpanElement> {
  /** The status value to render (also the default label). */
  status: string;
  /** Maps a status value to a badge variant. */
  variants: Record<string, BadgeVariant>;
  /** Variant for a status not present in `variants` (default "muted"). */
  fallback?: BadgeVariant;
}

/**
 * A `Badge` whose variant is derived from a status value — replaces the
 * `badge ${x === "a" ? "badge-success" : …}` ternary chains repeated across pages.
 * Renders the status as the label unless `children` is provided.
 */
export function StatusBadge({ status, variants, fallback = "muted", children, ...props }: StatusBadgeProps) {
  return (
    <Badge variant={variants[status] ?? fallback} {...props}>
      {children ?? status}
    </Badge>
  );
}

type AlertVariant = "error" | "success" | "warning" | "info";

interface AlertProps extends HTMLAttributes<HTMLDivElement> {
  variant?: AlertVariant;
}

const alertClasses: Record<AlertVariant, string> = {
  error: "alert-error",
  success: "alert-success",
  warning: "alert-warning",
  info: "alert-info",
};

export function Alert({ variant = "info", className, role, ...props }: AlertProps) {
  return (
    <div
      className={cx(alertClasses[variant], className)}
      role={role ?? (variant === "error" ? "alert" : "status")}
      aria-live={variant === "error" ? "assertive" : "polite"}
      {...props}
    />
  );
}

interface EmptyStateProps extends HTMLAttributes<HTMLDivElement> {
  title: string;
  description?: string;
  action?: ReactNode;
  framed?: boolean;
}

export function EmptyState({ title, description, action, framed = true, className, ...props }: EmptyStateProps) {
  return (
    <div className={cx(framed ? "card p-8 text-center" : "p-8 text-center", className)} {...props}>
      <p className="text-muted mb-4">{title}</p>
      {description && <p className="text-sm text-muted mb-6">{description}</p>}
      {action}
    </div>
  );
}

interface LoadingStateProps extends HTMLAttributes<HTMLDivElement> {
  label: string;
  framed?: boolean;
}

export function LoadingState({ label, framed = true, className, ...props }: LoadingStateProps) {
  return (
    <div
      className={cx(framed ? "card p-8 text-center text-muted" : "p-8 text-center text-muted", className)}
      role="status"
      aria-label={label}
      aria-live="polite"
      {...props}
    >
      <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
      <p className="text-sm">{label}...</p>
    </div>
  );
}

interface SkeletonBlockProps extends HTMLAttributes<HTMLDivElement> {
  label?: string;
}

export function SkeletonBlock({ label, className, ...props }: SkeletonBlockProps) {
  const block = (
    <div
      data-testid="skeleton-block"
      className={cx("animate-pulse rounded-control bg-surface-muted", className)}
      {...props}
    />
  );

  if (!label) return block;

  return (
    <div role="status" aria-label={label} aria-live="polite" aria-busy="true">
      {block}
    </div>
  );
}

interface PageHeaderProps extends HTMLAttributes<HTMLDivElement> {
  title: string;
  description?: string;
  actions?: ReactNode;
}

export function PageHeader({ title, description, actions, className, ...props }: PageHeaderProps) {
  return (
    <div
      className={cx("page-header flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between", className)}
      {...props}
    >
      <div>
        <h1 className="page-title">{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}

export type ConfidenceTier =
  "TRUSTED" | "HIGH" | "MEDIUM" | "LOW" | "DETERMINISTIC";

interface ConfidenceBadgeProps extends Pick<
  HTMLAttributes<HTMLSpanElement>,
  "className"
> {
  tier: ConfidenceTier;
}

const TIER_VARIANTS: Record<ConfidenceTier, BadgeVariant> = {
  TRUSTED: "success",
  HIGH: "info",
  MEDIUM: "warning",
  LOW: "muted",
  DETERMINISTIC: "success",
};

const TOOLTIP =
  "Deterministic system facts and manual entries are trusted; AI-extracted facts remain low until confirmed.";

export function ConfidenceBadge({
  tier,
  className,
}: ConfidenceBadgeProps) {
  return (
    <Badge
      variant={TIER_VARIANTS[tier]}
      className={`rounded-pill font-semibold ${className ?? ""}`}
      title={TOOLTIP}
    >
      {tier}
    </Badge>
  );
}

const PROVENANCE_LABELS: Record<DataProvenance, string> = {
  imported: "Imported",
  manual: "Manual",
  derived: "Derived",
};

const PROVENANCE_VARIANTS: Record<DataProvenance, BadgeVariant> = {
  imported: "success",
  manual: "warning",
  derived: "muted",
};

export function ProvenanceBadge({
  provenance,
  className,
}: {
  provenance?: DataProvenance | null;
  className?: string;
}) {
  if (!provenance) return null;

  const label = PROVENANCE_LABELS[provenance];
  return (
    <Badge
      variant={PROVENANCE_VARIANTS[provenance]}
      className={className}
      aria-label={`Provenance: ${label}`}
    >
      {label}
    </Badge>
  );
}
