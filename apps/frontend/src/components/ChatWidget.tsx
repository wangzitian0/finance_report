"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";

import ChatPanel from "@/components/ChatPanel";

export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  if (pathname === "/chat") {
    return null;
  }

  return (
    <div className="fixed bottom-6 right-6 z-50">
      <button
        onClick={() => setOpen((prev) => !prev)}
        className="group flex items-center gap-3 rounded-full bg-[#0f766e] px-5 py-3 text-sm font-semibold text-white shadow-xl shadow-emerald-200/60 transition hover:translate-y-[-2px]"
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white/15 text-lg">
          AI
        </span>
        <span className="uppercase tracking-[0.3em] text-xs">Ask AI</span>
      </button>

      {open ? (
        <div className="mt-4 w-[360px] rounded-[32px] border border-white/40 bg-[#f7f2e6]/95 p-4 shadow-2xl shadow-emerald-200/40 backdrop-blur">
          <ChatPanel variant="widget" onClose={() => setOpen(false)} />
        </div>
      ) : null}
    </div>
  );
}
