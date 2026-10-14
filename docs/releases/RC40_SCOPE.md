# rc40 final candidate scope

Includes RC38_COMMERCIAL_REPORT_CLOSURE and RC39_MAINTENANCE_GUARD. Neither earlier
candidate was activated. No clinical/cash/stock facts were written to validate
those candidates, and no required rollback image/data was pruned.

The new commercial-pricing panel has a scoped responsive layout: fieldsets and
controls shrink to their container, wide price tables scroll within the panel,
review actions wrap, and touch targets/checkbox descriptions remain readable.
Desktop and 390px visual verification uses mocked source records and is not
evidence of a live tenant approval or a Linux baseline update.

One reviewed sales constraint replacement, no row/column removal. All candidate
business changes remain subject to clean-checkout regression, PostgreSQL,
workspace, image-provenance, verified backup and VPS health gates. Windows stays
the unchanged signed managed release 1.0.5. Report source coverage is 62/100;
38 unavailable packs, customer-agreement/promotion authoring, Android signing,
provider onboarding and Managers' physical/real-stock acceptance remain open.

Live activation and exact CI/image/backup evidence will be recorded only after
successful deployment. Production remains rc37 until those gates pass.
