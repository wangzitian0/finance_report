import {
    BarChart3,
    Bell,
    BookOpen,
    ClipboardCheck,
    Clock,
    Home,
    Landmark,
    Link2,
    MessageSquare,
    ShieldCheck,
    SlidersHorizontal,
    UploadCloud,
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

// Three peers an everyday user needs. Notifications live in the header bell,
// not here. Everything internal lives under Advanced (see EPIC-022).
export const primaryWorkflowNavItems: NavItem[] = [
    { icon: UploadCloud, label: "Upload", href: "/upload", protected: true },
    { icon: BarChart3, label: "Reports", href: "/reports", protected: true },
    { icon: MessageSquare, label: "Chat", href: "/chat", protected: true },
];

export const advancedNavItems: NavItem[] = [
    { icon: Wallet, label: "Portfolio", href: "/portfolio", protected: true },
    { icon: Landmark, label: "Accounts", href: "/accounts", protected: true },
    { icon: BookOpen, label: "Journal", href: "/journal", protected: true },
    { icon: Link2, label: "Reconciliation", href: "/reconciliation", protected: true },
    { icon: Clock, label: "Processing", href: "/processing", protected: true },
    { icon: SlidersHorizontal, label: "AI Settings", href: "/settings/ai", protected: true },
];

export const ROUTE_CONFIG: Record<string, RouteConfig> = {
    "/": { label: "Home", Icon: Home },
    "/upload": { label: "Upload", Icon: UploadCloud },
    "/notifications": { label: "Notifications", Icon: Bell },
    "/attention": { label: "Needs attention", Icon: ShieldCheck },
    // Legacy routes redirect to the new IA; keep label/icon mappings so any
    // persisted workspace tabs or breadcrumbs render with the new names.
    "/dashboard": { label: "Home", Icon: Home },
    "/events": { label: "Notifications", Icon: Bell },
    "/accounts": { label: "Accounts", Icon: Landmark },
    "/journal": { label: "Journal", Icon: BookOpen },
    "/statements": { label: "Statements", Icon: UploadCloud },
    "/review": { label: "Review", Icon: ClipboardCheck },
    "/portfolio": { label: "Portfolio", Icon: Wallet },
    // Legacy /assets route redirects to /portfolio; keep its label mapping for
    // breadcrumbs and any persisted workspace tabs.
    "/assets": { label: "Portfolio", Icon: Wallet },
    "/portfolio/prices": { label: "Prices", Icon: Wallet },
    "/reports": { label: "Reports", Icon: BarChart3 },
    "/reports/balance-sheet": { label: "Balance Sheet", Icon: BarChart3 },
    "/reports/income-statement": { label: "Income Statement", Icon: BarChart3 },
    "/reports/cash-flow": { label: "Cash Flow", Icon: BarChart3 },
    "/reconciliation": { label: "Reconciliation", Icon: Link2 },
    "/reconciliation/unmatched": { label: "Unmatched", Icon: Link2 },
    "/reconciliation/review-queue": { label: "Review Queue", Icon: Link2 },
    "/processing": { label: "Processing", Icon: Clock },
    "/chat": { label: "Chat", Icon: MessageSquare },
    "/settings/ai": { label: "AI Settings", Icon: SlidersHorizontal },
    "/ping-pong": { label: "Ping-Pong", Icon: Zap },
};

export const DEFAULT_ROUTE_ICON = UploadCloud;

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
