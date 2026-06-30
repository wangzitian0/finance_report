"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import GeneralSettingsPage from "@/app/(main)/settings/general/page";
import AiSettingsPage from "@/app/(main)/settings/ai/page";
import LlmSettingsPage from "@/app/(main)/settings/llm/page";

type SettingsTab = "general" | "ai" | "llm";

const TABS: { id: SettingsTab; label: string }[] = [
    { id: "general", label: "General" },
    { id: "ai", label: "AI" },
    { id: "llm", label: "LLM Models" },
];

function normalizeTab(raw: string | null): SettingsTab {
    return raw === "ai" || raw === "llm" ? raw : "general";
}

// EPIC-022 AC22.21.4: the three formerly-separate Settings pages are merged into
// one tabbed surface. `/settings/general|ai|llm` redirect here with `?tab=`, so
// every settings entry point lands on the same page with the right tab active.
// The active tab stays in sync with `?tab=` so deep links and back/forward work.
export default function SettingsPage() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const urlTab = normalizeTab(searchParams.get("tab"));
    const [tab, setTab] = useState<SettingsTab>(urlTab);

    // Keep local state in sync when the URL query changes (back/forward, or a
    // direct navigation to /settings?tab=… while this component is mounted).
    useEffect(() => {
        setTab(urlTab);
    }, [urlTab]);

    const selectTab = (id: SettingsTab) => {
        setTab(id);
        router.replace(`/settings?tab=${id}`, { scroll: false });
    };

    // WAI-ARIA tabs keyboard pattern: Arrow keys move (and activate) the tab, and
    // focus follows to the newly active tab (required with roving tabindex).
    const onTablistKeyDown = (e: React.KeyboardEvent) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        e.preventDefault();
        const i = TABS.findIndex((t) => t.id === tab);
        const next = e.key === "ArrowRight" ? (i + 1) % TABS.length : (i - 1 + TABS.length) % TABS.length;
        const nextId = TABS[next].id;
        selectTab(nextId);
        document.getElementById(`settings-tab-${nextId}`)?.focus();
    };

    return (
        <div className="p-6">
            <div
                role="tablist"
                aria-label="Settings sections"
                onKeyDown={onTablistKeyDown}
                className="flex gap-1 border-b border-[var(--border)]"
            >
                {TABS.map((t) => (
                    <button
                        key={t.id}
                        type="button"
                        role="tab"
                        id={`settings-tab-${t.id}`}
                        aria-controls={`settings-panel-${t.id}`}
                        aria-selected={tab === t.id}
                        tabIndex={tab === t.id ? 0 : -1}
                        onClick={() => selectTab(t.id)}
                        className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
                            tab === t.id
                                ? "border-[var(--accent)] text-[var(--accent)]"
                                : "border-transparent text-muted hover:text-[var(--foreground)]"
                        }`}
                    >
                        {t.label}
                    </button>
                ))}
            </div>

            <div
                role="tabpanel"
                id={`settings-panel-${tab}`}
                aria-labelledby={`settings-tab-${tab}`}
                tabIndex={0}
                className="mt-2"
            >
                {tab === "general" && <GeneralSettingsPage />}
                {tab === "ai" && <AiSettingsPage />}
                {tab === "llm" && <LlmSettingsPage />}
            </div>
        </div>
    );
}
