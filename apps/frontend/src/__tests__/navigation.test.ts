import { it } from "vitest";
import * as N from "@/components/navigation";
import routeMap from "@/lib/route-map.json";
import { checkNavigationRoutes } from "./helpers/shellTestFixtures";

it("AC19.6.2 AC19.8.5 AC22.1-2 AC22.21 AC16.19.4 AC22.18.1 navigation", () => checkNavigationRoutes(N, routeMap.routes));
// AC-meta.fe-ia-nav.1 AC-meta.fe-ia-nav.5-6 AC-meta.fe-ia-nav.9 AC-meta.fe-ia-nav.20 AC-meta.fe-ia-nav.25-29 AC-meta.fe-ia-nav.36
