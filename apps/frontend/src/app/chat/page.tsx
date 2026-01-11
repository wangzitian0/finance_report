import { Suspense } from "react";

import ChatPageClient from "@/components/ChatPageClient";

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-[radial-gradient(circle_at_top,#f4efe6_0%,#f7f3ea_45%,#e3ece8_100%)] text-[#13201b]">
          <div className="mx-auto flex min-h-screen max-w-6xl items-center justify-center px-6">
            <span className="text-sm text-slate-500">Loading advisor...</span>
          </div>
        </div>
      }
    >
      <ChatPageClient />
    </Suspense>
  );
}
