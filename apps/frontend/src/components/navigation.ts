import {
    BarChart3,
    Bell,
    BookOpen,
    Clock,
    Coins,
    Cpu,
    ClipboardCheck,
    FileText,
    FolderOpen,
    Home,
    Landmark,
    Link2,
    MessageSquare,
    MoreHorizontal,
    Plus,
    ShieldCheck,
    SlidersHorizontal,
    TrendingDown,
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

// EPIC-022 AC22.21: mobile/PWA-first bottom tab bar, mirrored by the desktop
// sidebar. Exactly four routed tabs plus a center "Add" action (see ADD_ACTION).
// The accounting machinery is no longer a set of nav verbs — it lives in the
// on-demand `/audit` hub; low-frequency destinations live behind `/more`.
export const bottomTabItems: NavItem[] = [
    { icon: Home, label: "Home", href: "/", protected: false },
    { icon: MessageSquare, label: "Chat", href: "/chat", protected: true },
    { icon: ShieldCheck, label: "Audit", href: "/audit", protected: true },
    { icon: MoreHorizontal, label: "More", href: "/more", protected: true },
];

// The center tab is an action (opens the Add bottom sheet), not a route.
export const ADD_ACTION = { icon: Plus, label: "Add" } as const;

// `/audit` hub cards — verify-on-demand machinery folded out of navigation.
// Each deep-links to an existing page (which back-links to `/audit`).
export const auditHubItems: NavItem[] = [
    { icon: TrendingDown, label: "Trust", href: "/confidence", protected: true },
    { icon: Link2, label: "Reconciliation", href: "/reconciliation", protected: true },
    { icon: BookOpen, label: "Journal", href: "/journal", protected: true },
    { icon: Clock, label: "Processing", href: "/processing", protected: true },
];

// `/more` overflow — low-frequency destinations. Portfolio is conditional
// (rendered only when the user holds securities; gating happens in the page).
export const moreItems: NavItem[] = [
    { icon: Wallet, label: "Portfolio", href: "/portfolio", protected: true },
    { icon: SlidersHorizontal, label: "Settings", href: "/settings", protected: true },
];

// The genuine power/escape-hatch routes left after Audit and Settings absorb the
// rest. Rendered under an "Advanced" subheading on `/more`.
export const advancedItems: NavItem[] = [
    { icon: Landmark, label: "Accounts", href: "/accounts", protected: true },
];

export const ROUTE_CONFIG: Record<string, RouteConfig> = {
    "/": { label: "Home", Icon: Home },
    "/upload": { label: "Upload", Icon: UploadCloud },
    "/notifications": { label: "Notifications", Icon: Bell },
    "/attention": { label: "Needs attention", Icon: ShieldCheck },
    "/audit": { label: "Audit", Icon: ShieldCheck },
    "/more": { label: "More", Icon: MoreHorizontal },
    // Legacy routes redirect to the new IA; keep label/icon mappings so any
    // persisted workspace tabs or breadcrumbs render with the new names.
    // #1118: `/events` is permanently redirected to `/notifications` and is no
    // longer aliased here — `/notifications` is the single canonical path/label,
    // so the legacy "Notifications" label can no longer leak via the stale path.
    "/dashboard": { label: "Home", Icon: Home },
    "/accounts": { label: "Accounts", Icon: Landmark },
    "/journal": { label: "Journal", Icon: BookOpen },
    "/statements": { label: "Statements", Icon: UploadCloud },
    "/review": { label: "Review", Icon: ClipboardCheck },
    "/portfolio": { label: "Portfolio", Icon: Wallet },
    "/portfolio/evidence": { label: "Guided Evidence", Icon: FileText },
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
    "/confidence": { label: "Confidence Trend", Icon: TrendingDown },
    "/chat": { label: "Chat", Icon: MessageSquare },
    "/settings": { label: "Settings", Icon: SlidersHorizontal },
    "/settings/general": { label: "General Settings", Icon: Coins },
    "/settings/ai": { label: "AI Settings", Icon: SlidersHorizontal },
    "/settings/llm": { label: "LLM Models", Icon: Cpu },
    "/ping-pong": { label: "Ping-Pong", Icon: Zap },
};

export const DEFAULT_ROUTE_ICON = UploadCloud;

// Re-exported so the `/more` page can render the genuine power escape hatch.
export { FolderOpen };

/** Whether a nav item's href matches the current pathname (exact, or a path prefix). */
export function isActive(pathname: string, href: string): boolean {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(href + "/");
}

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
