"use client";

import { ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { WorkspaceProvider, useWorkspace } from "@/hooks/useWorkspace";
import { useSessionBootstrap } from "@/hooks/useSessionBootstrap";
import { Sidebar, WorkspaceTabs } from "@/components/AppNav";
import { ToastProvider } from "@/components/ui/Toast";
import { WorkflowNotificationCenter } from "@/components/workflow/WorkflowNotifications";
import { FirstRunModal } from "@/components/llm/FirstRunModal";
import { Download, Share2, X } from "lucide-react";
import { Button, IconButton } from "@/components/ui";
import { type PwaInstallState, usePwaInstall } from "@/hooks/usePwaInstall";
import { ADD_ACTION, bottomTabItems, isActive, type NavItem } from "@/components/navigation";
import { isAuthenticated } from "@/lib/auth";
import AddSheet from "@/components/shell/AddSheet";

interface AppShellProps {
    children: ReactNode;
}

function AppShellContent({ children }: AppShellProps) {
    const { isCollapsed } = useWorkspace();
    // Confirm/refresh the authenticated session against /auth/me on mount.
    useSessionBootstrap();

    return (
        <div className="pwa-safe-area-shell min-h-screen">
            <a
                href="#main-content"
                className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-toast focus:rounded-control focus:bg-surface-card focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-content focus:shadow-floating focus:outline-none focus:ring-2 focus:ring-accent"
            >
                Skip to main content
            </a>
            <Sidebar />

            {/* Main Content Area. On print, drop the sidebar offset so report
                output uses the full page (EPIC-022 #867 readable export). */}
            <div
                className={`transition-all duration-300 ease-in-out print:!ml-0 ${
                    isCollapsed ? "md:ml-16" : "md:ml-64"
                }`}
            >
                <div className="flex min-w-0 items-center border-b border-border bg-surface-card print:hidden">
                    <Link
                        href="/"
                        className="flex items-center gap-2 px-3 py-2 md:hidden"
                        aria-label="Finance Report home"
                    >
                        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-[var(--accent)] text-sm font-bold text-white">
                            $
                        </span>
                    </Link>
                    <div className="hidden md:block min-w-0 flex-1">
                        <WorkspaceTabs />
                    </div>
                    <WorkflowNotificationCenter />
                </div>
                <InstallAppPrompt />

                {/* Bottom padding on mobile so the fixed bottom tab bar never
                    covers page content. */}
                <main
                    id="main-content"
                    tabIndex={-1}
                    className="min-h-[calc(100dvh-4rem)] pb-[calc(5rem+env(safe-area-inset-bottom))] md:pb-0"
                >
                    {children}
                </main>
            </div>

            {/* EPIC-022 AC22.21.2: mobile/PWA-first bottom tab bar. */}
            <BottomTabBar />

            {/* First-run LLM provider prompt (EPIC-023 PR4): app-wide so it
                surfaces wherever the user lands while unconfigured. */}
            <FirstRunModal />
        </div>
    );
}

export function AppShell({ children }: AppShellProps) {
    return (
        <WorkspaceProvider>
            <ToastProvider>
                <AppShellContent>{children}</AppShellContent>
            </ToastProvider>
        </WorkspaceProvider>
    );
}

export type PwaInstallPromptViewState = PwaInstallState;

export function InstallAppPromptView({ state }: { state: PwaInstallPromptViewState }) {
    if (state.isInstalled || state.promptKind === null) return null;

    const isNativePrompt = state.promptKind === "native";

    return (
        <section
            aria-label="Install app"
            className="border-b border-border bg-surface-card px-4 py-3 print:hidden"
        >
            <div className="mx-auto flex max-w-5xl items-start gap-3">
                <div
                    className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-control bg-accent-muted text-accent"
                    aria-hidden="true"
                >
                    {isNativePrompt ? (
                        <Download className="h-5 w-5" />
                    ) : (
                        <Share2 className="h-5 w-5" />
                    )}
                </div>
                <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-content">
                        {isNativePrompt ? "Install Finance Report" : "Add Finance Report to Home Screen"}
                    </p>
                    <p className="mt-1 text-sm text-content-muted">
                        {isNativePrompt
                            ? "Use Finance Report from your home screen in a focused app window."
                            : "Open Share, then choose Add to Home Screen."}
                    </p>
                </div>
                <div className="flex flex-shrink-0 items-center gap-2">
                    {isNativePrompt ? (
                        <Button
                            aria-label="Install app"
                            className="px-3 py-1.5 text-sm"
                            onClick={() => void state.promptInstall()}
                        >
                            Install
                        </Button>
                    ) : null}
                    <IconButton
                        icon={X}
                        label="Dismiss install prompt"
                        className="h-8 w-8"
                        onClick={state.dismissPrompt}
                    />
                </div>
            </div>
        </section>
    );
}

export function InstallAppPrompt() {
    const installState = usePwaInstall();
    return <InstallAppPromptView state={installState} />;
}

// EPIC-022 AC22.21.2: the mobile/PWA-first bottom tab bar. Home · Chat · ⊕ Add ·
// Audit · More, with the center Add as an action (opens AddSheet), not a route.
// The desktop sidebar mirrors the same targets, so this renders on small screens
// only.
export function BottomTabBar() {
    const pathname = usePathname();
    const router = useRouter();
    const [addOpen, setAddOpen] = useState(false);
    // Read auth in an effect, not during render: isAuthenticated() returns false
    // on the server (no localStorage) but true on the client, which would render
    // a different tab set on each side and trip a hydration mismatch. Mirror the
    // Sidebar's pattern so SSR and the first client render agree.
    const [authed, setAuthed] = useState(false);
    useEffect(() => {
        setAuthed(isAuthenticated());
    }, [pathname]);

    const renderTab = (item: NavItem) => {
        const Icon = item.icon;
        const active = isActive(pathname, item.href);
        return (
            <Link
                key={item.href}
                href={item.href}
                className={`flex flex-1 flex-col items-center justify-center gap-0.5 py-2 text-xs transition-colors min-h-[44px] ${
                    active ? "text-[var(--accent)]" : "text-muted hover:text-[var(--foreground)]"
                }`}
                aria-current={active ? "page" : undefined}
            >
                <Icon className="h-5 w-5" aria-hidden="true" />
                <span>{item.label}</span>
            </Link>
        );
    };

    const [home, chat, audit, more] = bottomTabItems;
    const AddIcon = ADD_ACTION.icon;

    return (
        <>
            <nav
                className="fixed inset-x-0 bottom-0 z-40 flex items-stretch border-t border-[var(--border)] bg-[var(--background-card)] md:hidden print:hidden"
                style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
                aria-label="Primary"
            >
                {renderTab(home)}
                {authed && renderTab(chat)}
                {authed && (
                    <button
                        type="button"
                        onClick={() => setAddOpen(true)}
                        className="flex flex-1 flex-col items-center justify-center gap-0.5 py-2 text-xs text-[var(--accent)] min-h-[44px]"
                        aria-label={ADD_ACTION.label}
                    >
                        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[var(--accent)] text-white">
                            <AddIcon className="h-5 w-5" aria-hidden="true" />
                        </span>
                    </button>
                )}
                {authed && renderTab(audit)}
                {authed && renderTab(more)}
            </nav>

            <AddSheet
                isOpen={addOpen}
                onClose={() => setAddOpen(false)}
                onUploadComplete={() => router.refresh()}
            />
        </>
    );
}
