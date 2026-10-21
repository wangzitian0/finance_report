"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { ReactNode, useState } from "react";

import { createAppQueryClient } from "@/lib/queryClient";

export function Providers({ children }: { children: ReactNode }) {
    const [queryClient] = useState(createAppQueryClient);

    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
