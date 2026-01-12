import { Suspense } from "react";

import ChatPageClient from "@/components/ChatPageClient";

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <div className="p-6 flex items-center justify-center min-h-[60vh]">
          <span className="text-sm text-muted">Loading advisor...</span>
        </div>
      }
    >
      <ChatPageClient />
    </Suspense>
  );
}
