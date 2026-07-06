import { describe, it, expect, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";

import { useBodyScrollLock } from "@/hooks/useBodyScrollLock";

afterEach(() => {
    document.body.style.overflow = "";
    document.body.style.paddingRight = "";
});

describe("useBodyScrollLock (#1608)", () => {
    it("locks body scroll while open and restores on close", () => {
        const { rerender, unmount } = renderHook(
            ({ open }) => useBodyScrollLock(open),
            { initialProps: { open: false } },
        );
        expect(document.body.style.overflow).toBe("");

        rerender({ open: true });
        expect(document.body.style.overflow).toBe("hidden");

        rerender({ open: false });
        expect(document.body.style.overflow).toBe("");

        unmount();
    });

    it("compensates for the scrollbar width so desktop content does not shift", () => {
        // A visible scrollbar means innerWidth > documentElement.clientWidth.
        Object.defineProperty(window, "innerWidth", { value: 1024, configurable: true });
        Object.defineProperty(document.documentElement, "clientWidth", {
            value: 1009,
            configurable: true,
        });

        const { unmount } = renderHook(() => useBodyScrollLock(true));
        // The 15px gap left by the hidden scrollbar is padded back.
        expect(document.body.style.paddingRight).toBe("15px");

        unmount();
        expect(document.body.style.paddingRight).toBe("");
    });

    it("stays locked until the last of two overlapping locks releases", () => {
        const a = renderHook(() => useBodyScrollLock(true));
        const b = renderHook(() => useBodyScrollLock(true));
        expect(document.body.style.overflow).toBe("hidden");

        // Inner overlay closes; body must remain locked for the outer one.
        a.unmount();
        expect(document.body.style.overflow).toBe("hidden");

        b.unmount();
        expect(document.body.style.overflow).toBe("");
    });
});
