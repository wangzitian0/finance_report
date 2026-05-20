"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
    LayoutDashboard,
    FileText,
    Zap,
    Wallet,
    Menu,
    LucideIcon
} from "lucide-react";
import Sheet from "@/components/ui/Sheet";

interface NavItem {
    icon: LucideIcon;
    label: string;
    href: string;
}

const mobileNavItems: NavItem[] = [
    { icon: LayoutDashboard, label: "Dashboard", href: "/dashboard" },
    { icon: FileText, label: "Review", href: "/statements" },
    { icon: Zap, label: "Processing", href: "/processing" },
    { icon: Wallet, label: "Portfolio", href: "/portfolio" },
];

export function MobileNav() {
    const [isOpen, setIsOpen] = useState(false);
    const pathname = usePathname();

    return (
        <div className="md:hidden">
            <button
                onClick={() => setIsOpen(true)}
                className="p-2 text-muted hover:text-[var(--foreground)]"
                aria-label="Open navigation menu"
            >
                <Menu className="w-6 h-6" />
            </button>

            <Sheet
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title="Finance Report"
                width="max-w-xs"
            >
                <nav className="space-y-1">
                    {mobileNavItems.map((item) => {
                        const Icon = item.icon;
                        const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
                        
                        return (
                            <Link
                                key={item.href}
                                href={item.href}
                                onClick={() => setIsOpen(false)}
                                className={`
                                    flex items-center gap-3 px-3 py-4 rounded-md transition-colors text-base font-medium
                                    ${isActive 
                                        ? "bg-[var(--accent-muted)] text-[var(--accent)]" 
                                        : "text-muted hover:bg-[var(--background-muted)] hover:text-[var(--foreground)]"
                                    }
                                `}
                            >
                                <Icon className="w-6 h-6" />
                                {item.label}
                            </Link>
                        );
                    })}
                </nav>
            </Sheet>
        </div>
    );
}
