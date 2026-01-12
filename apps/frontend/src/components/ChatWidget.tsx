"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";

import ChatPanel from "@/components/ChatPanel";

export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  if (pathname === "/chat") return null;

  return (
    <div className="fixed bottom-6 right-6 z-50">
      <button
        onClick={() => setOpen((prev) => !prev)}
        className="flex items-center gap-2 rounded-md bg-[var(--accent)] px-4 py-2.5 text-sm font-medium text-white shadow-lg transition hover:bg-[var(--accent-hover)]"
      >
        <span className="w-6 h-6 rounded-md bg-white/20 flex items-center justify-center text-xs">AI</span>
        <span className="uppercase tracking-wide text-xs">Ask AI</span>
      </button>

      {open && (
        <div className="mt-3 w-[340px] card p-4">
          <ChatPanel variant="widget" onClose={() => setOpen(false)} />
        </div>
      )}
    </div>
  );
}
