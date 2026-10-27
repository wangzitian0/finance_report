"use client";

import { ReactNode } from "react";
import Link from "next/link";
import { WorkspaceProvider, useWorkspace } from "@/hooks/useWorkspace";
import { useSessionBootstrap } from "@/hooks/useSessionBootstrap";
import { Sidebar, WorkspaceTabs } from "@/components/AppNav";
import { BottomTabBar } from "@/components/shell/BottomTabBar";
import { ToastProvider } from "@/components/ui/Toast";
import { WorkflowNotificationCenter } from "@/components/workflow/WorkflowNotifications";
import { FirstRunModal } from "@/components/llm/FirstRunModal";
import { Download, Share2, X } from "lucide-react";
import { Button, IconButton } from "@/components/ui";
import { type PwaInstallState, usePwaInstall } from "@/hooks/usePwaInstall";

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
