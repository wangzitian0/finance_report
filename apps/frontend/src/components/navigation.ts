import {
    BarChart3,
    BookOpen,
    FileText,
    Home,
    Landmark,
    Link2,
    MessageSquare,
    MoreHorizontal,
    Plus,
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

export const APP_ROUTES = {
    HOME: "/",
    UPLOAD: "/upload",
    AUDIT: "/audit",
    MORE: "/more",
    CHAT: "/chat",
    ACCOUNTS: "/settings?tab=accounts",
    JOURNAL: "/journal",
    PORTFOLIO: "/portfolio",
    PORTFOLIO_EVIDENCE: "/portfolio?panel=evidence",
    PORTFOLIO_PRICES: "/portfolio?panel=prices",
    RECONCILIATION: "/reconciliation",
    RECONCILIATION_MATCHES: "/reconciliation?tab=matches",
    RECONCILIATION_UNMATCHED: "/reconciliation?tab=unmatched",
    RECONCILIATION_REVIEW_QUEUE: "/reconciliation?tab=review-queue",
    REPORTS: "/reports",
    SETTINGS: "/settings",
} as const;

/** The `/portfolio` URL that opens the holding drawer of one ticker. */
export function portfolioHoldingHref(ticker: string): string {
    return `${APP_ROUTES.PORTFOLIO}?ticker=${encodeURIComponent(ticker)}`;
}

// EPIC-022 AC22.21: mobile/PWA-first bottom tab bar, mirrored by the desktop
// sidebar. Exactly four routed tabs plus a center "Add" action (see ADD_ACTION).
// The accounting machinery is no longer a set of nav verbs — it lives in the
// on-demand `/audit` hub; low-frequency destinations live behind `/more`.
export const bottomTabItems: NavItem[] = [
    { icon: Home, label: "Home", href: APP_ROUTES.HOME, protected: false },
    { icon: MessageSquare, label: "Chat", href: APP_ROUTES.CHAT, protected: true },
    { icon: ShieldCheck, label: "Audit", href: APP_ROUTES.AUDIT, protected: true },
    { icon: MoreHorizontal, label: "More", href: APP_ROUTES.MORE, protected: true },
];

// The center tab is an action (opens the Add bottom sheet), not a route.
export const ADD_ACTION = { icon: Plus, label: "Add" } as const;

// `/audit` hub cards — verify-on-demand machinery folded out of navigation.
// Each deep-links to an existing page (which back-links to `/audit`).
export const auditHubItems: NavItem[] = [
    { icon: Link2, label: "Reconciliation", href: APP_ROUTES.RECONCILIATION, protected: true },
    { icon: BookOpen, label: "Journal", href: APP_ROUTES.JOURNAL, protected: true },
    { icon: UploadCloud, label: "Statements", href: APP_ROUTES.UPLOAD, protected: true },
];

// `/more` overflow — low-frequency destinations.
export const moreItems: NavItem[] = [
    { icon: Wallet, label: "Portfolio", href: APP_ROUTES.PORTFOLIO, protected: true },
    { icon: BarChart3, label: "Reports", href: APP_ROUTES.REPORTS, protected: true },
    { icon: SlidersHorizontal, label: "Settings", href: APP_ROUTES.SETTINGS, protected: true },
];

// The genuine power/escape-hatch routes left after Audit and Settings absorb the
// rest. Rendered under an "Advanced" subheading on `/more`.
export const advancedItems: NavItem[] = [
    { icon: Landmark, label: "Accounts", href: APP_ROUTES.ACCOUNTS, protected: true },
];

export const ROUTE_CONFIG: Record<string, RouteConfig> = {
    "/": { label: "Home", Icon: Home },
    "/upload": { label: "Upload", Icon: UploadCloud },
    "/audit": { label: "Audit", Icon: ShieldCheck },
    "/more": { label: "More", Icon: MoreHorizontal },
    "/journal": { label: "Journal", Icon: BookOpen },
    "/portfolio": { label: "Portfolio", Icon: Wallet },
    // A dynamic target page of route-map.json: `[id]` matches one path segment (see getRouteConfig).
    "/statements/[id]": { label: "Statement", Icon: UploadCloud },
    "/reports": { label: "Reports", Icon: BarChart3 },
    "/reconciliation": { label: "Reconciliation", Icon: Link2 },
    "/chat": { label: "Chat", Icon: MessageSquare },
    "/settings": { label: "Settings", Icon: SlidersHorizontal },
    "/ping-pong": { label: "Ping-Pong", Icon: Zap },
    "/login": { label: "Login", Icon: Landmark },
};

export const DEFAULT_ROUTE_ICON = UploadCloud;

/** Whether a nav item's href matches the current pathname (exact, or a path prefix). */
export function isActive(pathname: string, href: string): boolean {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(href + "/");
}

/** The `ROUTE_CONFIG` keys with a `[param]` segment, each with the pattern that matches one concrete path. */
const DYNAMIC_ROUTES = Object.keys(ROUTE_CONFIG)
    .filter((path) => path.includes("["))
    .map((path) => ({ path, pattern: new RegExp(`^${path.replace(/\[[^\]]+\]/g, "[^/]+")}$`) }));

export function getRouteConfig(pathname: string): RouteConfig {
    if (ROUTE_CONFIG[pathname]) return ROUTE_CONFIG[pathname];
    const dynamic = DYNAMIC_ROUTES.find(({ pattern }) => pattern.test(pathname));
    if (dynamic) return ROUTE_CONFIG[dynamic.path];
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
