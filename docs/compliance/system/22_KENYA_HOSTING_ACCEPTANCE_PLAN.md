<!-- TIBATRACE DOCUMENT BRANDING START -->
<p><img src="../brand/tibatrace-logo.jpeg" alt="TibaTrace logo" width="150"> &nbsp; <img src="../brand/esenai-group-logo.png" alt="Esenai Group logo" width="200"></p>

**TibaTrace · Esenai Group Ltd**<br>
Branding edition: 26 October 2026. Assessment dates, evidence scope and approval decisions below remain controlling.
<!-- TIBATRACE DOCUMENT BRANDING END -->

# Kenya hosting and DPIA acceptance plan

**Date:** 25 October 2026<br>
**Reviewed:** 26 October 2026; still not executed<br>
**Status:** NOT EXECUTED - Kenya capacity/provider and contract evidence required<br>
**Accountable owner:** Esenai Group Ltd / Sidney Chepkwony<br>
**Current state:** audited production rc71 VPS is in Hetzner Nuremberg, Germany.
The owner confirmed Kenya hosting needs arranging. No Kenya host or serving copy
has been supplied or verified.

## Architecture decision before provisioning

Have the privacy/legal owner determine the applicable localization and transfer
requirements. [General Regulations regulation 26](https://www.odpc.go.ke/wp-content/uploads/2024/03/THE-DATA-PROTECTION-GENERAL-REGULATIONS-2021-1.pdf)
addresses Kenya processing or at least one serving copy in Kenya for specified
purposes including primary/secondary healthcare. A foreign backup alone is not
evidence of a Kenya serving copy. Sensitive data transferred abroad also requires
the applicable lawful transfer basis and safeguards.

The proposed default is a primary Kenya deployment containing API, HQ, database,
clinical objects, queues, protected audit and coordinated recovery. Document
whether any foreign service/copy remains, why it is necessary, who can access it,
and its lawful safeguards. A Kenya domain, operator address or IPv4 geolocation
claim is insufficient: retain provider region/account/contract evidence for the
actual storage and serving system.

## Evidence and capacity required

1. Named provider/legal entity, Kenya datacentre/region, server identity,
   contract/DPA, subprocessor/support countries and access terms.
2. Approved primary/backup/key locations, at-rest encryption evidence, independent
   protected key custody and separate backup failure domain. Retain certificates
   and key recovery/rotation ownership outside source images and application logs.
3. A private administrative access path with named accounts, MFA, least privilege,
   service isolation, certificate validation and documented emergency recovery.
4. Sizing from measured CPU/RAM/storage/queue/database demand and forecast growth,
   including scanner, restore and rollback overhead. The current VPS has limited
   disk headroom; no new production scanner or restore workload should be assumed
   to fit without sizing.
5. Approved RPO/RTO and coordinated DB/object/config backup schedule/retention.
   Approve encryption, audit forwarding, monitoring and scanner operation before
   clinical upload/production onboarding acceptance.

No provider purchase or terms acceptance is performed by this plan. Once a Kenya
target is available, the deployment can be prepared against the approved scope.

## Migration and isolation procedure

1. Verify source revision/digests, migrations, registry provenance, current
   provider states, DNS, volumes and recoverable backup. Inventory patient,
   workforce, payment, stock, audit, attachment, credentials and device-bound state.
2. Provision the Kenya target with default-deny access, TLS, encrypted storage,
   separate backup/key protection and tested monitoring. Keep clinical/provider
   integrations disabled. Use synthetic data for first acceptance.
3. Rehearse a coordinated PostgreSQL/object/config restore in an isolated target
   with provider egress denied, scheduler/outbox delivery disabled and public user
   access closed. Restore only authorized data over protected transport. Keep
   client tokens, secret files and keys restricted; never embed them in artifacts.
4. Verify record counts/fingerprints, document decryption/integrity, tenant and
   role denial, identifier readback, clinical/payment/stock consistency, approved
   retention/hold reapplication and logs. A zero-object source still requires a
   separate synthetic encrypted-object and key recovery exercise.
5. Record measured recovery point/time, findings/retest and reviewer. Confirm
   functionality across HQ and each supported native-client release/device flow.
6. Plan a controlled write freeze/final consistent copy and DNS/TLS switch with
   the business owner. Ensure one authoritative writer and one scheduler; never
   run duplicate payment/exchange delivery during cutover.
7. Apply rollback criteria and a data-reconciliation decision. After new writes,
   DNS reversal alone is not a safe database rollback. Preserve the previous
   recovery set and avoid reversing additive DHA tables casually.
8. Verify final serving/storage locations, certificate validation, all data and
   logs/backup/key paths, service health, provider inactive state and tenant tests.
   Update the subprocessor, notice, retention and DPIA evidence records.
9. Retire foreign copies only under the approved retention/hold/contract decision;
   record authorized deletion and backup expiry. Do not delete the current host or
   its recovery set as an initial migration step.

## Acceptance record

| Gate | Required evidence | State |
|---|---|---|
| Kenya location and lawful flows | Region/account/contract, DPA/support countries, legal review and all remaining foreign copies | OPEN |
| Security | Privileged MFA, storage/key custody, verified TLS, scanner and protected audit | OPEN |
| Restore and integrity | Isolated coordinated restore, synthetic object recovery, record/tenant checks and measured RPO/RTO | OPEN |
| Workflow | HQ/native clients and clinical/payment/inventory acceptance on target | OPEN |
| Cutover | Single-writer/scheduler proof, DNS/TLS, final data reconciliation and rollback decision | OPEN |
| DPIA | Updated actual flow inventory, control retest, reviewer consultation and signed residual-risk decision | OPEN |

All gates must have named reviewers, dated outcomes and inspectable evidence. A
new VPS address or deployment success alone does not close the DPIA.
