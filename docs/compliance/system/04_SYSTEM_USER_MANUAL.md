# TibaTrace System User Manual

**Applies to:** operational workflows documented against the product; deployed server baseline rc71 (25 October 2026). Native-client binary versions and physical devices require separate release-inventory verification.<br>
**Audience:** platform owners, tenant administrators, pharmacy managers, cashiers, pharmacists, inventory and reporting staff  
**Companion:** [existing end-to-end guide](../../TIBATRACE_USER_GUIDE.md); that guide is historical. Confirm each workflow against the current tenant configuration and exact installed client before operational use.

## 1. Before you begin

- Use the account issued to you; never share passwords, PINs, or POS sessions.
- Your actions depend on your tenant, branch, role, and assigned capabilities. A menu being visible does not grant permission; the server is authoritative.
- Enter patient and practitioner information only for an authorized care or operating purpose. Confirm identifiers and source evidence before marking them verified.
- Use the supported managed till installer for counter work. Server deployments do not update Windows or Android clients automatically.
- If the screen reports a blocked, stale, unknown, or unreconciled state, stop and resolve that state. Do not work around clinical, payment, stock, or authorization gates.

## 2. Sign in and select your workspace

1. Open the TibaTrace URL provided by your organization.
2. Sign in using your own account. If the account is temporary, replace the temporary password before continuing.
3. Choose only a tenant and branch you are authorized to access. Tenant users cannot use platform-owner functions or switch into another tenant's records.
4. If a menu or action is absent, request the exact capability from your tenant administrator. Do not use another person's account.
5. Sign out on a shared workstation and lock or close the till at the end of the shift.

## 3. Platform owner and tenant administration

Platform-owner administration is limited to explicitly designated platform-owner accounts. Tenant administrators manage their own organization and staff only.

Typical setup sequence:

1. Create or activate the tenant and its organization/branch records.
2. Add tenant users with named individual accounts.
3. Assign the minimum role/capabilities required for each job; keep approval and review duties separate where the workflow requires independent approval.
4. Configure branch, inventory location, registers, product catalogue, units, tax/pricing rules, and approved payment options.
5. Review the audit record after material access, configuration, and approval changes.

Do not use demo/sandbox records for live trading. A tenant administrator cannot grant platform-owner access.

## 4. Catalogue, purchasing, and inventory

### Catalogue and prices

- Import the tenant's approved catalogue and pricing file through the supported bulk-import workflow.
- Resolve each row's product identity, pack unit, SKU, barcode if available, tax category, and effective price. Review the validation report and correct rejected or ambiguous rows before posting.
- An imported item is not automatically a received or saleable stock batch.

### Receive stock

1. Match the goods to the purchase order or authorized receipt.
2. Record the actual product, pack/unit conversion, quantity, batch number, expiry date, supplier and source documents.
3. Quarantine damaged, expired, recalled, or uncertain items. Only release stock after the required authorized check.
4. Confirm posted quantities against the delivery and inventory balance.

### Transfers and stocktakes

- Create a transfer request from the source location, select the destination and item/batch quantities, and submit it for the configured approval/dispatch/receipt steps.
- Do not treat a request as completed stock movement until each required state is recorded.
- For stocktake, count by location, product and batch. Resolve variance with a second authorized reviewer when required. Do not overwrite ledger history to force a balance.

## 5. Point of sale and pharmacy workflows

### Open a till

1. Confirm the correct branch and device are active and assigned to you.
2. Confirm the register session, opening float, business date, and any required prior-day Z report/closure.
3. If the register reports an unresolved payment or unreconciled session, reconcile it with the manager before trading.

### Retail checkout

1. Scan or search the correct item and confirm quantity and price.
2. Review the basket. Stock is reserved before payment; the basket is held stable during payment.
3. Record cash or the supported external-terminal card reference. A card reference is not proof of an integrated card settlement. M-PESA/Daraja remains unavailable unless the tenant's approved integration is configured and validated.
4. Complete the full balance. The sale, stock issue and receipt are finalized only when settlement is complete. If a payment is collected but stock completion fails, use the recovery action shown by the till; do not create a second sale.
5. Refunds and unfinished-payment voids require the configured independent supervisor. Returned goods remain quarantined until assessed.

### Prescription dispensing

1. Search/select the intended patient and prescription; verify identity and prescription provenance.
2. Complete pharmacist review, allergy/interaction and other required clinical checks. Escalate findings requiring pharmacist intervention.
3. Select the correct product, strength, form, batch and quantity. Do not dispense expired, quarantined, recalled, or unavailable stock.
4. Record permitted substitutions, overrides, counselling and independent approvals with the required reason/evidence.
5. Settle payment and record handover/collection only after the workflow gates are satisfied.

Clinical or regulatory uncertainty should be escalated to the responsible pharmacist/manager, not resolved by selecting an unsupported value.

## 6. Register close and reconciliation

1. Complete or recover all pending transactions and payments.
2. Count physical cash, compare against the till's cash ledger, and record variance with an explanation.
3. Produce the Z report and close each register session.
4. Close the business day only after all sessions are closed and required reports are recorded.
5. If a payment outcome is unknown, reconcile it against the authoritative provider or external terminal before closing; an acknowledgement or zero balance alone is not settlement evidence.

## 7. Reports, audit, and regulatory workspaces

- Use reports only within your authorized tenant and purpose. Validate report filters, date range, and scope before export.
- Keep exported patient-level data secure and delete local copies when the approved purpose ends.
- Audit views show governed actions; they do not replace a full infrastructure or security log review.
- Regulatory recalls and tenant response workflows must follow the regulator notice and local manager process. A manual notice is not evidence of an automated regulator integration.
- Disease/IDSR reporting and KNHTS exchange specifications in this repository are not a user-facing live submission path. Follow the authorized MoH/County workflow until a formally approved interface is released.

## 8. When something goes wrong

- **Cannot sign in:** use the approved reset route or contact your administrator. Do not share temporary credentials in email/chat.
- **Wrong tenant/branch or access denied:** stop; ask the administrator to review your assigned access.
- **Payment status unknown:** do not retry as a new sale. Use payment recovery/reconciliation and manager escalation.
- **Stock or clinical safety mismatch:** stop dispensing/sale and ask the pharmacist or inventory manager to resolve the source record.
- **Suspected data exposure, lost device, malware, or unusual access:** report immediately to the tenant manager and privacy/security contact using the [Incident Response Plan](07_INCIDENT_RESPONSE_PLAN.md).

## 9. Version note

The server rc71 record does not establish which Windows or Android client versions are installed at each site. Check the signed installer catalogue, tenant/device inventory and release acceptance record before distributing this manual as version-specific or installing a newer client.
