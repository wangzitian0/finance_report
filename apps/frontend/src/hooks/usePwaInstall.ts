"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

export const PWA_INSTALL_DISMISSED_AT_KEY = "finance-report:pwa-install-dismissed-at";
const DISMISS_COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000;

type BeforeInstallPromptOutcome = "accepted" | "dismissed";

type BeforeInstallPromptEvent = Event & {
    prompt: () => Promise<void>;
    userChoice: Promise<{ outcome: BeforeInstallPromptOutcome; platform: string }>;
};

export type PwaInstallPromptKind = "native" | "ios" | null;

export interface PwaInstallState {
    isInstalled: boolean;
    canPrompt: boolean;
    promptKind: PwaInstallPromptKind;
    promptInstall: () => Promise<void>;
    dismissPrompt: () => void;
}

function hasBrowserWindow() {
    return typeof window !== "undefined";
}

function readDismissedAt() {
    if (!hasBrowserWindow()) return null;

    const raw = window.localStorage.getItem(PWA_INSTALL_DISMISSED_AT_KEY);
    if (!raw) return null;

    const timestamp = Number.parseInt(raw, 10);
    return Number.isFinite(timestamp) ? timestamp : null;
}

function hasActiveDismissal() {
    const dismissedAt = readDismissedAt();
    if (!dismissedAt) return false;

    return Date.now() - dismissedAt < DISMISS_COOLDOWN_MS;
}

export function isIosLikeNavigator() {
    if (!hasBrowserWindow()) return false;

    const { maxTouchPoints, platform, userAgent } = window.navigator;
    const iPhoneOrPad = /iPad|iPhone|iPod/.test(platform) || /iPad|iPhone|iPod/.test(userAgent);
    const touchMac = platform === "MacIntel" && maxTouchPoints > 1;

    return iPhoneOrPad || touchMac;
}

export function isStandaloneDisplay() {
    if (!hasBrowserWindow()) return false;

    const navigatorWithStandalone = window.navigator as Navigator & { standalone?: boolean };
    const mediaStandalone = window.matchMedia?.("(display-mode: standalone)").matches ?? false;

    return mediaStandalone || navigatorWithStandalone.standalone === true;
}

export function usePwaInstall(): PwaInstallState {
    const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
    const [isDismissed, setIsDismissed] = useState(false);
    const [isInstalled, setIsInstalled] = useState(false);
    const [isIos, setIsIos] = useState(false);

    useEffect(() => {
        setIsDismissed(hasActiveDismissal());
        setIsInstalled(isStandaloneDisplay());
        setIsIos(isIosLikeNavigator());

        const handleBeforeInstallPrompt = (event: Event) => {
            event.preventDefault();

            if (hasActiveDismissal() || isStandaloneDisplay()) {
                setDeferredPrompt(null);
                return;
            }

            setDeferredPrompt(event as BeforeInstallPromptEvent);
            setIsDismissed(false);
        };

        const handleAppInstalled = () => {
            window.localStorage.removeItem(PWA_INSTALL_DISMISSED_AT_KEY);
            setDeferredPrompt(null);
            setIsDismissed(false);
            setIsInstalled(true);
        };

        const displayMode = window.matchMedia?.("(display-mode: standalone)");
        const handleDisplayModeChange = () => setIsInstalled(isStandaloneDisplay());

        window.addEventListener("beforeinstallprompt", handleBeforeInstallPrompt);
        window.addEventListener("appinstalled", handleAppInstalled);
        displayMode?.addEventListener?.("change", handleDisplayModeChange);

        return () => {
            window.removeEventListener("beforeinstallprompt", handleBeforeInstallPrompt);
            window.removeEventListener("appinstalled", handleAppInstalled);
            displayMode?.removeEventListener?.("change", handleDisplayModeChange);
        };
    }, []);

    const dismissPrompt = useCallback(() => {
        if (hasBrowserWindow()) {
            window.localStorage.setItem(PWA_INSTALL_DISMISSED_AT_KEY, String(Date.now()));
        }
        setDeferredPrompt(null);
        setIsDismissed(true);
    }, []);

    const promptInstall = useCallback(async () => {
        if (!deferredPrompt) return;

        const prompt = deferredPrompt;
        setDeferredPrompt(null);
        await prompt.prompt();

        const choice = await prompt.userChoice;
        if (choice.outcome === "accepted") {
            window.localStorage.removeItem(PWA_INSTALL_DISMISSED_AT_KEY);
            setIsDismissed(false);
            setIsInstalled(true);
            return;
        }

        dismissPrompt();
    }, [deferredPrompt, dismissPrompt]);

    const promptKind = useMemo<PwaInstallPromptKind>(() => {
        if (isInstalled || isDismissed) return null;
        if (deferredPrompt) return "native";
        if (isIos) return "ios";
        return null;
    }, [deferredPrompt, isDismissed, isInstalled, isIos]);

    return {
        isInstalled,
        canPrompt: promptKind === "native",
        promptKind,
        promptInstall,
        dismissPrompt,
    };
}
