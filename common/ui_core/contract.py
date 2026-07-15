from common.meta.base.package_contract import (
    ACRecord,
    ConceptRecord,
    PackageContract,
)
contract = PackageContract(
    name="ui_core",
    tier="CODE-ONLY",
    depends_on=[],
    events=[],
    interface=["api_client_pattern", "app_config_router"],
    concepts=[
        ConceptRecord(
            key="api_client_pattern",
            owner="apps/frontend/frontend-patterns.md",
            description="Frontend MUST use lib/api.ts wrapper; never raw fetch().",
            family="frontend",
            cross_refs=[
                "AGENTS.md",
                "docs/agents/red-lines.md",
                "apps/frontend/src/lib/api.ts",
            ],
        ),
    ],
    invariants=[],
    roadmap=[
              ACRecord(
            id="AC-ui_core.16.23.2",
            statement="TransactionTable supports inline edit of `amount`, `description`, `date` with optimistic update + server confirm; failed write reverts row and shows error toast",
            test="Manual UI test",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ui_core.16.23.5",
            statement="Mobile navigation renders below 768 px (originally the `<MobileNav />` drawer; replaced by the `<BottomTabBar />` bottom tab bar per EPIC-022 AC22.21); the desktop sidebar is hidden on mobile",
            test="Manual UI test",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ui_core.16.11.32",
            statement="Vitest harness for Stage 1 split components — shared `renderReviewComponent()` helper in `apps/frontend/src/__tests__/helpers/`",
            test="Manual UI test",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ui_core.15.7.8",
            statement="Dashboard Processing card shows the signed current balance and a non-zero balance warning",
            test="`shows the current Processing Account balance when transfers are unresolved`",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ui_core.1.10.4",
            statement="Frontend production dependency audits fail CI and CSP forbids `unsafe-eval` in shipped responses",
            test="`src/__tests__/api-urls.test.ts`, `.github/workflows/ci.yml`",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-ui_core.16.1.2",
            statement="**Stage 1 UI shows PDF + parsed split view**",
            test="Manual UI test",
            priority="P0",
            status="done",
        ),
          ACRecord(
            id="AC-ui_core.16.23.1",
            statement="Two-stage review UI capability (DROPPED)",
            test="TODO",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-ui_core.19.11.1",
            statement="Event-driven upload to report UX (DROPPED)",
            test="TODO",
            priority="P0",
            status="done",
        ),
    
        ACRecord(
            id="AC-ui_core.16.23.1",
            epic=16,
            epic_name="two-stage-review-ui",
            description="Two-stage review UI capability",
            mandatory=False,
            status="dropped",
        ),

        ACRecord(
            id="AC-ui_core.19.11.1",
            epic=19,
            epic_name="event-driven-upload-to-report-ux",
            description="Event-driven upload to report UX",
            mandatory=False,
            status="dropped",
        ),
    ],
)
