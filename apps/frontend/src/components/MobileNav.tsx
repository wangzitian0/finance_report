"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, FolderOpen, Menu } from "lucide-react";
import Sheet from "@/components/ui/Sheet";
import { advancedNavItems, primaryWorkflowNavItems } from "@/components/navigation";

export function MobileNav() {
    const [isOpen, setIsOpen] = useState(false);
    const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);
    const pathname = usePathname();
    const isAdvancedActive = advancedNavItems.some((item) => pathname === item.href || pathname.startsWith(item.href + "/"));
    const closeNavigation = () => {
        setIsOpen(false);
        setIsAdvancedOpen(false);
    };

    return (
        <div className="md:hidden">
            <button
                onClick={() => setIsOpen(true)}
                className="inline-flex h-11 w-11 items-center justify-center text-muted hover:text-[var(--foreground)]"
                aria-label="Open navigation menu"
            >
                <Menu className="w-6 h-6" />
            </button>

            <Sheet
                isOpen={isOpen}
                onClose={closeNavigation}
                title="Finance Report"
                width="max-w-xs"
            >
                <nav className="space-y-1" aria-label="Mobile navigation">
                    {primaryWorkflowNavItems.map((item) => {
                        const Icon = item.icon;
                        const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
                        
                        return (
                            <Link
                                key={item.href}
                                href={item.href}
                                onClick={closeNavigation}
                                className={`
                                    flex items-center gap-3 px-3 py-4 rounded-md transition-colors text-base font-medium
                                    ${isActive 
                                        ? "bg-[var(--accent-muted)] text-[var(--accent)]" 
                                        : "text-muted hover:bg-[var(--background-muted)] hover:text-[var(--foreground)]"
                                    }
                                `}
                            >
                                <Icon className="w-6 h-6" aria-hidden="true" />
                                {item.label}
                            </Link>
                        );
                    })}

                    <div className="pt-1">
                        <button
                            type="button"
                            onClick={() => setIsAdvancedOpen((open) => !open)}
                            className={`
                                flex w-full items-center gap-3 rounded-md px-3 py-4 text-base font-medium transition-colors
                                ${isAdvancedActive
                                    ? "bg-[var(--accent-muted)] text-[var(--accent)]"
                                    : "text-muted hover:bg-[var(--background-muted)] hover:text-[var(--foreground)]"
                                }
                            `}
                            aria-expanded={isAdvancedOpen}
                        >
                            <FolderOpen className="h-6 w-6" aria-hidden="true" />
                            <span>Advanced</span>
                            <ChevronDown
                                className={`ml-auto h-5 w-5 transition-transform ${isAdvancedOpen ? "rotate-180" : ""}`}
                                aria-hidden="true"
                            />
                        </button>

                        {isAdvancedOpen && (
                            <div className="mt-1 space-y-1 pl-3">
                                {advancedNavItems.map((item) => {
                                    const Icon = item.icon;
                                    const isActive = pathname === item.href || pathname.startsWith(item.href + "/");

                                    return (
                                        <Link
                                            key={item.href}
                                            href={item.href}
                                            onClick={closeNavigation}
                                            className={`
                                                flex items-center gap-3 rounded-md px-3 py-3 text-base font-medium transition-colors
                                                ${isActive
                                                    ? "bg-[var(--accent-muted)] text-[var(--accent)]"
                                                    : "text-muted hover:bg-[var(--background-muted)] hover:text-[var(--foreground)]"
                                                }
                                            `}
                                        >
                                            <Icon className="h-5 w-5" aria-hidden="true" />
                                            {item.label}
                                        </Link>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                </nav>
            </Sheet>
        </div>
    );
}
