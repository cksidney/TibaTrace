# rc41 candidate — exact approver identity scope (held; superseded by rc42)

The exact rc41 SQLite backend suite passed all 2,119 tests. Production image
publication was nevertheless blocked by one HQ test-helper timing failure: it
attempted to select a list before the timer-backed options form was mounted.
No rc41 image was published or activated. rc42 fixes that test synchronization
and adds delayed-initial-options coverage without changing backend business
code or native POS source. PostgreSQL validation remains mandatory.

Includes the commercial pricing, six source-report, maintenance-admin and
responsive UI scope of RC38/39/40. None of those candidates was activated.

rc40 full-suite evidence: 2,116 passed, one tenant-lookup audit failure. Publication
looked up the reviewer by UUID before its capability check. rc41 records the
reviewer's actual identity tenant in the approval event and requires that exact
identity scope when reloading for publication. A reviewer moved to another
tenant cannot leave a usable approval. Explicit tenant-less platform reviewers
remain supported, with fresh target-tenant authority checked. Tests cover both.

The lookup audit is unchanged; no model/global exemption or suppression was
added. Mandatory real PostgreSQL validation is now included directly in this
candidate's production-image workflow before image publication, alongside SQLite
full regression. Exact source/database and JUnit evidence remain required.

No new migration beyond reviewed sales 0005; no Windows/Android source change.
Windows stays signed managed-device 1.0.5. Unsupported report packs, governed
customer agreement/promotion authoring, provider onboarding, Android signing,
Manager stock/hardware acceptance and VPS capacity remain separately open.
Production remains rc37 until all gates, backup and live verification pass.
