# TibaTrace Privacy Policy — Draft

**Status:** Draft for controller/legal review; not approved for publication<br>
**Effective date:** To be set by the publishing data controller<br>
**Controller/contact:** Must be completed before publication

> Do not publish this draft until the named controller, privacy contact, lawful bases, data-sharing recipients, hosting locations, and retention periods have been verified. A tenant may be the controller for patient records while Esenai Group Ltd acts as its processor under contract; the actual relationship must be confirmed for each processing activity.

## Who is responsible

For patient-care records entered by a pharmacy or healthcare organization, that organization generally decides why and how the records are used. It is expected to act as data controller. TibaTrace is the software service. Esenai Group Ltd is identified as the vendor in system documentation and may act as a processor when it handles records only on the tenant's instructions. The parties' contracts and actual activities determine the legal roles.

**Controller:** `[Legal name and address of tenant/controller]`<br>
**Privacy/DPO contact:** `[Approved email, phone, and postal address]`<br>
**Service provider:** Esenai Group Ltd, `[registered address and privacy contact to confirm]`

## Personal information the service may process

Depending on the tenant's enabled workflows, TibaTrace may process:

- patient identity and contact details, identifiers, allergies, conditions, prescriptions, dispensing, encounters, and related clinical documents;
- practitioner identity, licence/authority claims, verification evidence and organization roles;
- tenant user accounts, roles, sessions, device credentials and security events;
- pharmacy branches, product catalogue, batches, stock, purchasing, sales, cash and payment references;
- customer, supplier, insurer/claim and operational records; and
- technical data such as request identifiers, timestamps, device/app version, and audit events.

The tenant should not enter data that is not needed for the stated care, safety, legal, or business purpose. Sensitive patient identifiers are encrypted in the application and shown masked in ordinary views; access to reveal is separately authorized and audited.

## Why information is used

The tenant may use information to provide and document care, verify prescriptions, dispense medicines safely, manage stock and recalls, operate the pharmacy, reconcile transactions, meet legal/regulatory duties, prevent fraud, and protect system access. The controller must identify and document the lawful basis and applicable health-data condition for each purpose. Consent is used only where appropriate and must be specific and voluntary.

The service uses account and technical data to authenticate users, enforce roles and tenant boundaries, protect the platform, investigate incidents, and maintain auditability. Data is not used for unrelated advertising or model training by this policy.

## Who information may be shared with

Information is available to authorized users within the same tenant according to their role and purpose. TibaTrace is designed to isolate tenant records. It may be disclosed to service providers or authorities only under the controller's documented instructions, a lawful requirement, or another valid legal basis.

National registry, insurer, payment, terminology, or surveillance exchanges must not be assumed active merely because the product has an integration template or specification. The controller should identify the recipient and data fields in its notice before any such connection is enabled.

## Where information is stored and transferred

The documented deployment uses a hosted API, PostgreSQL, Redis, and tenant-keyed clinical document storage, accessed over HTTPS. The audited server country on 25 October 2026 is Germany (Hetzner Nuremberg); the application database target, clinical-object volume and inspected release backups are on that VPS. The owner confirmed Kenya hosting needs arranging. Correct the final notice after the [Kenya deployment acceptance](22_KENYA_HOSTING_ACCEPTANCE_PLAN.md); support countries and all subprocessors still require complete disclosure before publication. Any transfer outside Kenya requires a documented assessment and safeguards under applicable law.

## Security

The service implements role/capability checks, tenant-scoped access, audit records, HTTPS production settings, encryption of patient identifiers, and integrity checks for clinical attachments. These technical controls reduce risk but cannot eliminate every risk. Administrators and users must protect credentials and use only their own accounts. See the [Information Security Policy](06_INFORMATION_SECURITY_POLICY.md) and [Encryption Specification](08_ENCRYPTION_IMPLEMENTATION_SPECIFICATION.md).

## Retention

The TibaTrace system owner has stated a seven-year retention baseline. The period's start trigger and exceptions must be defined by record class; the controller must confirm that the configured schedule fits its purposes and applicable clinical, pharmacy, financial, employment and other rules. Legal holds may extend retention, and data should be erased, anonymized or returned when no longer required. See the [Data Retention and Disposal Policy](16_DATA_RETENTION_AND_DISPOSAL_POLICY.md). This draft is not publication-ready until the actual schedule and system behavior are verified.

## Your rights and requests

Subject to applicable law, a person may ask the controller to confirm whether their data is processed, access it, correct inaccurate details, object to or restrict processing, request deletion where applicable, or request portability. Some records may need to be retained or processing may continue where the law permits or requires it. The controller will verify identity, route the request to the correct tenant, record the decision, and respond within applicable legal timelines.

**Submit a request to:** `[Controller privacy contact]`<br>
If the concern is not resolved, a person may contact the [Office of the Data Protection Commissioner](https://www.odpc.go.ke/).

## Children and representatives

Where children or people who cannot act for themselves use pharmacy services, the controller must apply the legal safeguards for capacity, parental/guardian authority, best interests, and permitted health-care disclosures. This draft does not replace those clinical and legal procedures.

## Changes and complaints

The controller will date and publish material changes to this notice and preserve prior versions. Data-protection complaints may be raised with the controller using the contact above or with the ODPC.

## Governing references

This draft should be reviewed against Kenya's [Data Protection Act, 2019](https://new.kenyalaw.org/akn/ke/act/2019/24/eng@2019-11-15/source), [Data Protection (General) Regulations, 2021](https://www.odpc.go.ke/wp-content/uploads/2024/03/THE-DATA-PROTECTION-GENERAL-REGULATIONS-2021-1.pdf), and applicable digital-health instruments. It is not legal advice.
