import { Sidebar } from "@/components/Sidebar";
import { WorkspaceTabs } from "@/components/WorkspaceTabs";
import { AppShell } from "@/components/AppShell";

export default function MainLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <AppShell>
            <div className="flex h-screen bg-[var(--background)]">
                <Sidebar />
                <main className="flex-1 flex flex-col min-w-0 transition-all duration-300 ease-in-out bg-[var(--background)]">
                    <WorkspaceTabs />
                    <div className="flex-1 overflow-auto">
                        {children}
                    </div>
                </main>
            </div>
        </AppShell>
    );
}
