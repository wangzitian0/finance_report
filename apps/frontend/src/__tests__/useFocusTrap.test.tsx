import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useRef } from "react";
import { useFocusTrap } from "@/hooks/useFocusTrap";

describe("useFocusTrap", () => {
    it("returns early when container is not present", () => {
        const ref = { current: null } as any;
        const { result } = renderHook(() => useFocusTrap(ref, true));
        // no exception thrown
        expect(result).toBeDefined();
    });

    it("wraps Tab to first element when on last element without shift", () => {
        const container = document.createElement("div");
        const btn1 = document.createElement("button");
        const btn2 = document.createElement("button");
        container.appendChild(btn1);
        container.appendChild(btn2);
        document.body.appendChild(container);

        const ref = { current: container } as any;
        renderHook(() => useFocusTrap(ref, true));

        // focus last
        btn2.focus();
        const ev = new KeyboardEvent("keydown", { key: "Tab", bubbles: true });
        Object.defineProperty(ev, "shiftKey", { get: () => false });
        act(() => container.dispatchEvent(ev));

        expect(document.activeElement).toBe(btn1);

        container.remove();
    });
});
