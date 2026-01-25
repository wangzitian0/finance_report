"use client";

import { createContext, useContext, useState, useCallback, useEffect, useRef, ReactNode } from "react";

type ToastType = "success" | "error" | "info" | "warning";

interface Toast {
    id: number;
    message: string;
    type: ToastType;
}

interface ToastContextType {
    showToast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

export function useToast() {
    const context = useContext(ToastContext);
    if (!context) {
        throw new Error("useToast must be used within a ToastProvider");
    }
    return context;
}

interface ToastProviderProps {
    children: ReactNode;
}

export function ToastProvider({ children }: ToastProviderProps) {
    const [toasts, setToasts] = useState<Toast[]>([]);
    const timeoutRefs = useRef<Map<number, NodeJS.Timeout>>(new Map());
    const idCounterRef = useRef(0);

    // Cleanup timeouts on unmount
    useEffect(() => {
        const refs = timeoutRefs.current;
        return () => {
            refs.forEach((timeout) => clearTimeout(timeout));
            refs.clear();
        };
    }, []);

    const showToast = useCallback((message: string, type: ToastType = "success") => {
        const id = ++idCounterRef.current;
        setToasts((prev) => [...prev, { id, message, type }]);

        const timeout = setTimeout(() => {
            setToasts((prev) => prev.filter((t) => t.id !== id));
            timeoutRefs.current.delete(id);
        }, 3000);
        
        timeoutRefs.current.set(id, timeout);
    }, []);

    const removeToast = useCallback((id: number) => {
        const timeout = timeoutRefs.current.get(id);
        if (timeout) {
            clearTimeout(timeout);
            timeoutRefs.current.delete(id);
        }
        setToasts((prev) => prev.filter((t) => t.id !== id));
    }, []);

    return (
        <ToastContext.Provider value={{ showToast }}>
            {children}
            <div 
                role="region"
                aria-live="polite"
                aria-label="Notifications"
                className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2"
            >
                {toasts.map((toast) => (
                    <div
                        key={toast.id}
                        role={toast.type === "error" ? "alert" : "status"}
                        className={`px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 min-w-[280px] max-w-[400px] animate-slide-up ${
                            toast.type === "success" ? "bg-[var(--success)] text-white" :
                            toast.type === "error" ? "bg-[var(--error)] text-white" :
                            toast.type === "warning" ? "bg-[var(--warning)] text-black" :
                            "bg-[var(--info)] text-white"
                        }`}
                    >
                        <span className="text-lg" aria-hidden="true">
                            {toast.type === "success" && "✓"}
                            {toast.type === "error" && "✕"}
                            {toast.type === "warning" && "⚠"}
                            {toast.type === "info" && "ℹ"}
                        </span>
                        <span className="flex-1 text-sm font-medium">{toast.message}</span>
                        <button
                            onClick={() => removeToast(toast.id)}
                            className="opacity-70 hover:opacity-100"
                            aria-label="Dismiss notification"
                        >
                            ✕
                        </button>
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    );
}
