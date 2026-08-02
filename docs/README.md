# TibaTrace documentation

**Start here: [TIBATRACE_USER_GUIDE.md](TIBATRACE_USER_GUIDE.md)** — the
authoritative end-to-end guide. Install, configure, dispense, report, operate.

Everything else in this directory is either deeper detail behind one section of
that guide, or a dated record that must not be rewritten. The difference
matters, so it is set out explicitly below.

---

## Authoritative

| Document | Covers |
|---|---|
| [TIBATRACE_USER_GUIDE.md](TIBATRACE_USER_GUIDE.md) | The whole system, for every role |
| [deployment/TIBATRACE_RELEASE_PACKAGING_WORKFLOW.md](deployment/TIBATRACE_RELEASE_PACKAGING_WORKFLOW.md) | How a release is built, signed and shipped |

## Reference — domain and architecture

Deeper than the guide, and still current.

| Area | Where |
|---|---|
| Domain models (48 documents) | [`domain/`](domain/) |
| System architecture | [`architecture/`](architecture/) |
| Architecture decision records | [`adr/`](adr/) |
| FHIR and Kenya conformance | [`fhir/`](fhir/) |
| DHA compliance | [`compliance/dha/`](compliance/dha/) |
| National integrations | [`integrations/`](integrations/) |
| Clinical decision support | [`cds/`](cds/) |
| Security | [`security/`](security/) |
| Data migrations and crosswalks | [`migrations/`](migrations/) |
| Release notes, one per candidate | [`releases/`](releases/) |

## Superseded

Folded into the end-to-end guide. Each carries a banner pointing at the section
that replaced it. Kept because the engineering detail and the history are worth
having; the guide wins where they disagree.

- `POS_CLINICAL_WORKFLOW_GUIDE.md` → guide §4.2
- `POS_PAYMENT_WORKFLOW_GUIDE.md` → guide §4.2
- `SCAN_TO_RECEIVE_GUIDE.md` → guide §3.5
- `PURCHASING_INVENTORY_ARCHITECTURE.md` → guide §3.5, §5.1

## Records — do not rewrite

These are **dated evidence**, not documentation. They record what was assessed,
by whom, on a given date, and several carry a formal decision. Rewriting one to
match today's system destroys the thing that makes it useful — and for a
regulated healthcare product, some of it is the audit trail.

If the system has moved on, add a new record. Do not edit an old one.

| Document | What it records |
|---|---|
| `POS_UI_UX_CERTIFICATION.md` | Formal decision (`POS_UI_UX_BLOCKED`), 357 lines |
| `POS_UI_UX_CURRENT_STATE_AUDIT.md` | Audit against a named baseline commit |
| `POS_HARDWARE_CERTIFICATION.md` | Hardware assessment, dated 2026-07-28 |
| `POS_ACCESSIBILITY_REPORT.md` | Accessibility certification |
| `POS_USABILITY_VALIDATION.md` | Usability validation |
| `POS_VISUAL_REGRESSION_REPORT.md` | Visual regression certification |
| `POS_PHYSICAL_VALIDATION_RUNBOOK.md` | Physical validation status |
| `PRICING_AUTHORITY_DECISION.md` | Pricing authority decision, settled by evidence 2026-07-27 |
| `POS_DESIGN_SYSTEM.md` | Design system certification |
| `POS_UI_UX_ARCHITECTURE.md` | UI/UX architecture as certified |
| `validation/`, `testing/`, `phase_2/`, `source/` | Phase evidence and validation records |

---

## Contributing

Corrections go in the guide. If the guide and the system disagree, the guide is
wrong until proven otherwise — fix it, in the same change that fixes the system.
