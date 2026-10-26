# TibaTrace DHA change and certification-governance policy — draft

**Updated:** 26 October 2026<br>
**Policy status:** Draft; not adopted or signed<br>
**Production evidence baseline:** server `1.0.0-rc71`, commit `2965194a29311314e8a5772adfeee5af8c14a8f2`<br>
**DHA certificate status:** Owner-declared; reference and conditions not verified in reviewed evidence.

This draft sets internal evidence controls for changes to a system that may be in a DHA-regulated category. It does not state that every change requires recertification or impose a regulatory deadline. DHA's current certificate conditions and written instructions govern; obtain DHA's determination when scope is unclear. The previous rc5 policy and unsupported annual/30-day assertions are withdrawn.

## 1. Scope and roles

Apply to changes to the TibaTrace server, database/schema, clinical workflow, patient identity, security/access, encryption, retention, hosting, native clients, integrations and operational controls. Assign a change owner, release owner, privacy/DPO reviewer, clinical safety reviewer and security reviewer as applicable. The accountable operator approves internal release; DHA, facility and tenant/controller approval remain separate where required.

## 2. Change assessment

Before approval, record:

- change summary, reason, affected service/tenants/data and risk/clinical impact;
- source branch/commit, build artifacts, configuration and migration/rollback plan;
- whether processing purpose, data categories, recipients, location, retention or access changes;
- whether patient safety, privacy risk, certificate scope, assessed version or integration conformance changes;
- DPIA/security/clinical/privacy review and tests required;
- whether the current DHA certificate/conditions or DHA's written instruction require notification, amendment, testing or reassessment; retain the exact authority reference;
- tenant/controller approvals and credentials process for any tenant-specific exchange.

If this assessment indicates new high-risk processing or a material DPIA change, update the DPIA before enabling that purpose. If certification scope is uncertain, keep the feature/connection disabled while requesting DHA direction.

## 3. Release and evidence controls

1. Preserve the old release record. Do not rewrite historical production evidence after a later deployment.
2. Run the normal engineering, security, privacy, clinical, migration, backup and rollback gates for the exact source.
3. Record server and client versions, immutable artifact hashes, database migrations, deployment environment, tenant configuration and approvers.
4. Update the traceability matrix only with current criterion source/version, actual result and linked evidence. A source test alone does not prove production operation or DHA acceptance.
5. Obtain DHA written direction/approval and tenant/facility authorization before changing a regulated interface or expanding the approved scope.
6. After release, verify live configuration, health, access controls, audit, integration state and rollback readiness; capture dated evidence and re-evaluate residual risk.

## 4. Review and retention

The policy owner must set an internal review cadence when adopting this policy. Revisit it after a security/privacy incident, significant architecture or purpose change, certificate condition, DHA direction, new facility/interface or material legal change. Keep the change record and authority correspondence under the approved evidence-retention schedule.

**Policy owner:** Esenai Group Ltd accountable service owner — to assign<br>
**Privacy/legal review:** pending<br>
**Clinical/security review:** pending<br>
**Approval date/signature:** pending

Check the [DHA regulatory guide](https://certification.dha.go.ke/regulatory-guide) and exact certificate conditions at the time of each submission. This draft is not a DHA change approval or recertification decision.
