import {
    BarChart3,
    Bell,
    BookOpen,
    ClipboardCheck,
    Clock,
    FileText,
    Landmark,
    LayoutDashboard,
    Link2,
    MessageSquare,
    Wallet,
    Zap,
    type LucideIcon,
} from "lucide-react";

export interface NavItem {
    icon: LucideIcon;
    label: string;
    href: string;
    protected: boolean;
}

export interface RouteConfig {
    label: string;
    Icon: LucideIcon;
}

export const primaryNavItems: NavItem[] = [
    { icon: LayoutDashboard, label: "Dashboard", href: "/dashboard", protected: true },
    { icon: Bell, label: "Events", href: "/events", protected: true },
    { icon: Landmark, label: "Accounts", href: "/accounts", protected: true },
    { icon: BookOpen, label: "Journal", href: "/journal", protected: true },
    { icon: FileText, label: "Statements", href: "/statements", protected: true },
    { icon: ClipboardCheck, label: "Review", href: "/review", protected: true },
    { icon: Wallet, label: "Portfolio", href: "/portfolio", protected: true },
    { icon: BarChart3, label: "Reports", href: "/reports", protected: true },
    { icon: Link2, label: "Reconciliation", href: "/reconciliation", protected: true },
    { icon: Clock, label: "Processing", href: "/processing", protected: true },
    { icon: MessageSquare, label: "AI Advisor", href: "/chat", protected: true },
];

export const ROUTE_CONFIG: Record<string, RouteConfig> = {
    "/dashboard": { label: "Dashboard", Icon: LayoutDashboard },
    "/events": { label: "Events", Icon: Bell },
    "/accounts": { label: "Accounts", Icon: Landmark },
    "/journal": { label: "Journal", Icon: BookOpen },
    "/statements": { label: "Statements", Icon: FileText },
    "/review": { label: "Review", Icon: ClipboardCheck },
    "/assets": { label: "Portfolio", Icon: Landmark },
    "/portfolio": { label: "Portfolio", Icon: Wallet },
    "/portfolio/prices": { label: "Prices", Icon: Wallet },
    "/reports": { label: "Reports", Icon: BarChart3 },
    "/reports/balance-sheet": { label: "Balance Sheet", Icon: BarChart3 },
    "/reports/income-statement": { label: "Income Statement", Icon: BarChart3 },
    "/reports/cash-flow": { label: "Cash Flow", Icon: BarChart3 },
    "/reconciliation": { label: "Reconciliation", Icon: Link2 },
    "/reconciliation/unmatched": { label: "Unmatched", Icon: Link2 },
    "/reconciliation/review-queue": { label: "Review Queue", Icon: Link2 },
    "/processing": { label: "Processing", Icon: Clock },
    "/chat": { label: "AI Advisor", Icon: MessageSquare },
    "/ping-pong": { label: "Ping-Pong", Icon: Zap },
};

export const DEFAULT_ROUTE_ICON = FileText;

export function getRouteConfig(pathname: string): RouteConfig {
    if (ROUTE_CONFIG[pathname]) return ROUTE_CONFIG[pathname];
    const segments = pathname.split("/").filter(Boolean);
    while (segments.length > 0) {
        const parentPath = "/" + segments.join("/");
        if (ROUTE_CONFIG[parentPath]) return ROUTE_CONFIG[parentPath];
        segments.pop();
    }
    const derivedSegments = pathname.split("/").filter(Boolean);
    const lastSegment = derivedSegments[derivedSegments.length - 1];
    const rawLabel = lastSegment ?? "Page";
    const label = rawLabel.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    return { label, Icon: DEFAULT_ROUTE_ICON };
}
