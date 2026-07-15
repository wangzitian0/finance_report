"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { ADD_ACTION, bottomTabItems, isActive, type NavItem } from "@/components/navigation";
import { isAuthenticated } from "@/lib/auth";
import AddSheet from "@/components/shell/AddSheet";

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
