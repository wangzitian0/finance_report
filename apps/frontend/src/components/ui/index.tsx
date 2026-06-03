import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

function cx(...classes: Array<string | false | null | undefined>) {
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

interface IconButtonProps extends Omit<ButtonProps, "children"> {
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
      className={cx("inline-flex h-9 w-9 items-center justify-center p-2", className)}
      aria-label={label}
      title={title ?? label}
      {...props}
    >
      <Icon className="h-4 w-4" aria-hidden="true" />
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
