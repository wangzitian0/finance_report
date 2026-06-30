"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/ui";
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
export default function SettingsPage() {
    const searchParams = useSearchParams();
    const [tab, setTab] = useState<SettingsTab>(() => normalizeTab(searchParams.get("tab")));

    return (
        <div className="p-6">
            <PageHeader title="Settings" description="Manage your account, AI behaviour, and language models." />

            <div role="tablist" aria-label="Settings sections" className="mt-4 flex gap-1 border-b border-[var(--border)]">
                {TABS.map((t) => (
                    <button
                        key={t.id}
                        type="button"
                        role="tab"
                        aria-selected={tab === t.id}
                        onClick={() => setTab(t.id)}
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

            <div className="mt-2">
                {tab === "general" && <GeneralSettingsPage />}
                {tab === "ai" && <AiSettingsPage />}
                {tab === "llm" && <LlmSettingsPage />}
            </div>
        </div>
    );
}
