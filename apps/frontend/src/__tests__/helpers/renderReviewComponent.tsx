import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ToastProvider } from "@/components/ui/Toast";
import { ReactNode } from "react";

export function renderReviewComponent(
    ui: ReactNode,
    queryClient: QueryClient = new QueryClient({
        defaultOptions: {
            queries: {
                retry: false,
            },
        },
    }),
) {

    return render(
        <QueryClientProvider client={queryClient}>
            <ToastProvider>
                {ui}
            </ToastProvider>
        </QueryClientProvider>
    );
}
