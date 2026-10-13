# rc36 workflow closure and acceptance register

This is the implementation follow-up to the 13 October surface audit, not a
claim of regulatory, hardware or exhaustive business certification. Deployment
and test results must be recorded separately against the final commit.

| Finding | Software change | Residual acceptance/dependency |
| --- | --- | --- |
| F01 terminal-state integrity | Canonical payment/supply ownership, cancellation and payload-bound retries; negative controls | Production smoke must not fabricate sales/clinical facts |
| F02 minimum-necessary reads | Explicit capabilities, branch scope, cashier clinical redaction and clinical-access audit | Managers approve user role assignments; no automatic broad grant |
| F03 clinical journey | HQ paper-Rx/episode origination; native reserve/allocate/prepare/independent checklist; explicit counselling/collection | Actual licensed staff must perform independent clinical decisions |
| F04 retail refunds | Original receipt lookup, independent approval, immutable cash refund, quarantine returns and till reconciliation | Managers validate real cash/return handling with controlled acceptance data |
| F05 settled-collection reporting | Combined retail/clinical collections and refunds, separate currencies/channels | Not accrual revenue, VAT or profit certification |
| F06 source-to-trade onboarding | Linked reviewed-item mapping, governed price publication and actual stock custody/quality | TransElgon pack units, real batches/expiry and Manager evidence still required |
| F07 identity report taxonomy | Real User/Role/capability events selected and audited | Tenant supervisors review grants |
| F08 incomplete reports | 56 bounded, source-backed packs; prerequisites for 44 unavailable packs | No fabricated GL, valuation, forecasting or provider certification |
| F09/F10 HQ operator paths/collections | Commerce creation and actual stock-to-delivery commands; safe paging/search/refresh | Genuine customer/address/stock and independent seal/POD evidence |
| F11 legacy browser till | Installer handoff at `/pos/`; no obsolete browser execution contracts | Install and activate supported native devices |
| F12 stocktake exceptions | Full scope snapshot, recount/void/cancel and independent contributor approval | Physical count evidence and reasons remain operator acts |
| F13 jobs/integrations | Scheduled tenant expiry projection; provider templates remain disabled | Approved provider endpoints/keys and real recall feeds still absent |
| Windows printing | Installed OS-driver transport; immutable receipt/label snapshot, durable outcomes and reasoned reprints | Managers inspect paper, scanner and printer-connected drawer; no guessed drawer pulses |
| Android release | Shared/native software workflow changes validated as source | Approved release-signing key and installed-device/hardware acceptance pending |

Stage 2D.2 prototype/certification drafts are preserved outside the release.
Production must keep rc35 rollback material and take a new verified database
backup before applying the four reviewed migrations. Windows 1.0.5 is published
only after configured signing, timestamp, checksum and clean-install checks.
