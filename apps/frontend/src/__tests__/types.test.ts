import { describe, it, expect } from "vitest";
import * as Types from "../lib/types";

describe("lib/types.ts", () => {
    it("imports successfully", () => {
        expect(Types).toBeDefined();
    });
});
