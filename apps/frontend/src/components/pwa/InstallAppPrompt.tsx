"use client";

import { Download, Share2, X } from "lucide-react";
import { Button, IconButton } from "@/components/ui";
import { type PwaInstallState, usePwaInstall } from "@/hooks/usePwaInstall";

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
