import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

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

interface TableSkeletonProps extends HTMLAttributes<HTMLDivElement> {
  label: string;
  rows?: number;
  columns?: number;
}

export function TableSkeleton({
  label,
  rows = 5,
  columns = 4,
  className,
  ...props
}: TableSkeletonProps) {
  return (
    <div
      role="status"
      aria-label={label}
      aria-live="polite"
      aria-busy="true"
      className={cx("card p-5", className)}
      {...props}
    >
      <div className="space-y-3" aria-hidden="true">
        {Array.from({ length: rows }).map((_, rowIndex) => (
          <div
            key={rowIndex}
            className="grid gap-3"
            style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
          >
            {Array.from({ length: columns }).map((__, columnIndex) => (
              <SkeletonBlock
                key={columnIndex}
                className={cx(
                  "h-4",
                  columnIndex === 0 && "w-full",
                  columnIndex > 0 && columnIndex < columns - 1 && "w-4/5",
                  columnIndex === columns - 1 && "ml-auto w-2/3",
                )}
              />
            ))}
          </div>
        ))}
      </div>
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
