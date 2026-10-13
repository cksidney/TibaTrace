"""Minimum-necessary clinical, till and access-governance source reports."""

from apps.cds.pos_screening_models import PosClinicalFinding, PosClinicalOverride, PosClinicalScreening
from apps.documents.models import DocumentAccessEvent
from apps.identity.models import Role, ServiceAccount, UserRole
from apps.identity.pos_authentication import PosSession
from apps.pos_shift.models import CashExceptionReview, RegisterSession, ShiftReport
from apps.prescription.models import DispensingEpisode, MedicineSupply, PharmacistIntervention

OPERATOR_SNAPSHOTS = {"sec-access-grants", "sec-capability-matrix", "sec-service-accounts"}
OPERATOR_REPORTS = OPERATOR_SNAPSHOTS | {
    "clin-screening", "clin-interactions", "clin-overrides", "clin-allergy", "clin-interventions",
    "sales-clinical-holds", "sales-clinical-overrides", "sales-rx-dispensing", "sales-by-pharmacist", "sales-waiting-time",
    "hr-register-sessions", "hr-x-reports", "hr-z-reports", "hr-cash-variance",
    "sec-cash-exceptions", "sec-forced-closures", "sec-session-assurance", "sec-document-access",
}


def _s(value):
    if value is None:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def query_operator_report(report_id, tenant_id, actor, window):
    from .queries import ReportData, _authority, _bounded, _period
    _authority(actor, tenant_id, ["reports.view"])
    if report_id not in OPERATOR_REPORTS:
        raise NotImplementedError("No validated operator source query is available.")
    if report_id in OPERATOR_SNAPSHOTS and window:
        raise ValueError("This is a current-state access snapshot; remove reporting-window filters.")

    def result(basis, columns, rows):
        return ReportData(basis, columns, [[_s(v) for v in row] for row in rows])

    if report_id.startswith("clin-") or report_id.startswith("sales-"):
        _authority(actor, tenant_id, ["clinical.read", "prescriptions.clinical_review", "prescriptions.pharmacist_verify"])
        if report_id in {"clin-screening", "sales-clinical-holds"}:
            qs = _period(PosClinicalScreening.all_objects.filter(tenant_id=tenant_id), "evaluated_at", window)
            if report_id == "sales-clinical-holds":
                qs = qs.filter(safe_to_proceed=False)
            return result("Recorded clinical screenings by evaluation timestamp; holds are screening refusals, not cancelled sales. Patient identity, basket context and clinical free text excluded. This is not a regulator submission or clinical safety certification.",
                ["Screening ID", "Evaluated at", "Branch ID", "Status", "Mode", "Severity", "Blocking findings", "Requires pharmacist", "Safe to proceed", "Rule version", "Offline"],
                [[r.screening_id, r.evaluated_at, r.branch_id, r.status, r.screening_mode, r.highest_severity, r.blocking_count,
                  r.requires_pharmacist, r.safe_to_proceed, r.rule_set_version, r.offline_state] for r in _bounded(qs.order_by("evaluated_at", "pk"))])
        if report_id == "clin-interactions":
            qs = _period(PosClinicalFinding.all_objects.filter(tenant_id=tenant_id, category="DRUG_DRUG_INTERACTION"), "detected_at", window).order_by("detected_at", "pk")
            return result("Recorded drug-drug findings by detection time. Clinical narratives and patient identifiers omitted; a finding is not a proven adverse event.",
                ["Finding ID", "Screening ID", "Detected at", "Rule reference", "Rule version", "Severity", "Blocking", "Resolution", "Resolved at"],
                [[r.pk, r.screening_id, r.detected_at, r.rule_id_ref, r.rule_version, r.severity, r.blocking, r.resolution_status, r.resolved_at] for r in _bounded(qs)])
        if report_id in {"clin-overrides", "sales-clinical-overrides"}:
            qs = _period(PosClinicalOverride.all_objects.filter(tenant_id=tenant_id), "created_at", window).order_by("created_at", "pk")
            return result("Clinical override request cohorts by creation time with current lifecycle projection. Approved/consumed/revoked are distinct, not all approvals; supporting notes, conditions and patient context omitted.",
                ["Override ID", "Requested at", "Finding ID", "Reason code", "Status", "Requested by", "Approved by", "Approved at", "Consumed at", "Revoked at", "Expires at", "Rule version"],
                [[r.pk, r.created_at, r.finding_id, r.override_reason, r.status, r.requested_by_id, r.pharmacist_id,
                  r.approved_at, r.consumed_at, r.revoked_at, r.expires_at, r.rule_version] for r in _bounded(qs)])
        if report_id == "clin-allergy":
            qs = _period(PosClinicalFinding.all_objects.filter(tenant_id=tenant_id, category="DRUG_ALLERGY"), "detected_at", window).order_by("detected_at", "pk")
            return result("Recorded drug-allergy screening findings and current acknowledgement/resolution by detection timestamp. Patient identifiers, allergy reactions and clinical narratives omitted; alerts are not independently confirmed allergy prevalence.",
                ["Finding ID", "Screening ID", "Detected at", "Severity", "Blocking", "Resolution", "Resolved by", "Resolved at", "Rule version"],
                [[r.pk, r.screening_id, r.detected_at, r.severity, r.blocking, r.resolution_status, r.resolved_by_id, r.resolved_at, r.rule_version] for r in _bounded(qs)])
        if report_id == "clin-interventions":
            qs = _period(PharmacistIntervention.all_objects.filter(tenant_id=tenant_id), "created_at", window).order_by("created_at", "pk")
            return result("Pharmacist intervention records created within the window and their current outcome; clinical instructions, contact details and patient identity omitted.",
                ["Intervention ID", "Created at", "Type", "Status", "Outcome", "Actor ID"],
                [[r.pk, r.created_at, r.intervention_type, r.status, r.outcome, r.actor_id] for r in _bounded(qs)])
        if report_id in {"sales-rx-dispensing", "sales-by-pharmacist"}:
            qs = _period(MedicineSupply.all_objects.filter(tenant_id=tenant_id), "supplied_at", window).select_related("episode__branch").order_by("supplied_at", "pk")
            return result("Authoritative medicine supply facts by supplied timestamp. Operator IDs identify the accountable supply actor, not a licence certification. This is clinical supply activity, not monetary sales revenue.",
                ["Supply ID", "Supplied at", "Branch", "Episode ID", "Supply actor ID", "Status"],
                [[r.pk, r.supplied_at, r.episode.branch.code, r.episode_id, r.supplied_by_id, r.status] for r in _bounded(qs)])
        qs = _period(DispensingEpisode.all_objects.filter(tenant_id=tenant_id), "initiated_at", window).select_related("branch").order_by("initiated_at", "pk")
        return result("Episode cohorts by initiation timestamp; duration is only initiation-to-completion where both actual timestamps exist. Missing completion stays blank, not zero; no queue SLA threshold or estimated waiting time is fabricated.",
            ["Episode ID", "Branch", "Initiated at", "Completed at", "Current status", "Elapsed completion seconds"],
            [[r.pk, r.branch.code, r.initiated_at, r.completed_at, r.status,
              (r.completed_at - r.initiated_at).total_seconds() if r.completed_at else None] for r in _bounded(qs)])

    if report_id.startswith("hr-") or report_id in {"sec-cash-exceptions", "sec-forced-closures"}:
        _authority(actor, tenant_id, ["pos.shift.manage"])
        if report_id in {"hr-register-sessions", "sec-forced-closures"}:
            qs = RegisterSession.all_objects.filter(tenant_id=tenant_id).select_related("register__location")
            field = "closed_at" if report_id == "sec-forced-closures" else "opened_at"
            qs = _period(qs, field, window)
            if report_id == "sec-forced-closures":
                qs = qs.filter(forced_closure=True)
            return result("Register-session observations by " + field + "; open/closed states are current projections, not a recalculated Z. Free-text forced-closure reasons omitted.",
                ["Session ID", "Branch", "Register", "Opened at", "Opened by", "Closed at", "Closed by", "State", "Forced closure"],
                [[r.pk, r.register.location.code, r.register.code, r.opened_at, r.opened_by_id, r.closed_at, r.closed_by_id, r.state, r.forced_closure] for r in _bounded(qs.order_by(field, "pk"))])
        if report_id == "sec-cash-exceptions":
            qs = _period(CashExceptionReview.all_objects.filter(tenant_id=tenant_id), "opened_at", window).select_related("report").order_by("opened_at", "pk")
            return result("Cash exception review records by investigation opening time; review status does not rewrite the signed Z report. Investigation notes omitted.",
                ["Review ID", "Report number", "Opened at", "Opened by", "Status", "Resolved at", "Resolved by"],
                [[r.pk, r.report.report_number, r.opened_at, r.opened_by_id, r.status, r.resolved_at, r.resolved_by_id] for r in _bounded(qs)])
        qs = _period(ShiftReport.all_objects.filter(tenant_id=tenant_id), "generated_at", window).select_related("register_session__register__location").order_by("generated_at", "pk")
        qs = qs.filter(report_type="X" if report_id == "hr-x-reports" else "Z")
        rows = []
        for r in _bounded(qs):
            cash, variance = r.snapshot.get("cash") or {}, r.snapshot.get("variance") or {}
            rows.append([r.report_number, r.generated_at, r.register_session.register.location.code,
                r.register_session.register.code, r.snapshot.get("currency", ""), cash.get("opening"), cash.get("cash_sales"),
                cash.get("cash_refunds"), cash.get("expected_closing"), variance.get("declared"), variance.get("difference"),
                variance.get("classification"), r.closure_type])
        return result("Persisted " + ("X interim cumulative" if report_id == "hr-x-reports" else "Z final") + " report snapshots by generation time. Figures are never recomputed from today's transactions, currencies stay separate; no human productivity ranking inferred.",
            ["Report number", "Generated at", "Branch", "Register", "Currency", "Opening cash", "Cash sales", "Cash refunds", "Expected closing", "Declared", "Variance", "Classification", "Closure"], rows)

    _authority(actor, tenant_id, ["identity.manage", "audit.read"])
    if report_id == "sec-access-grants":
        qs = UserRole.all_objects.filter(tenant_id=tenant_id, user__tenant_id=tenant_id, role__tenant_id=tenant_id).select_related("user", "role").order_by("user_id", "role_id")
        return result("Current tenant role assignments; active flags retained. Role assignments are not a complete effective ABAC access decision; privileged platform accounts are governed separately.",
            ["User ID", "User active", "Role", "Assignment active", "Role active", "Assigned at"],
            [[r.user_id, r.user.is_active, r.role.code, r.is_active, r.role.is_active, r.created_at] for r in _bounded(qs)])
    if report_id == "sec-capability-matrix":
        qs = Role.all_objects.filter(tenant_id=tenant_id).order_by("code", "pk")
        return result("Current tenant role capability declarations. JSON arrays retained as declarations; ABAC denies, session assurance and platform privileges remain separate controls, not a claim of every user's effective permissions.",
            ["Role", "Active", "System role", "Capabilities"], [[r.code, r.is_active, r.is_system, sorted(r.capabilities or [])] for r in _bounded(qs)])
    if report_id == "sec-service-accounts":
        qs = ServiceAccount.all_objects.filter(tenant_id=tenant_id).order_by("code", "pk")
        return result("Current service-account governance declarations. Credential material/fingerprints are deliberately excluded; declared capabilities are not evidence of credential rotation or live provider approval.",
            ["Service code", "Display name", "Active", "Capabilities", "Created at"], [[r.code, r.display_name, r.is_active, sorted(r.capabilities or []), r.created_at] for r in _bounded(qs)])
    if report_id == "sec-document-access":
        qs = _period(DocumentAccessEvent.all_objects.filter(tenant_id=tenant_id), "created_at", window).order_by("created_at", "pk")
        return result("Immutable clinical-document access audit events by recorded time. Document content, names, URLs and denial-reason text omitted.",
            ["Event ID", "Recorded at", "Document ID", "Actor ID", "Action", "Outcome"], [[r.pk, r.created_at, r.document_id, r.actor_id, r.action, r.outcome] for r in _bounded(qs)])
    qs = _period(PosSession.all_objects.filter(tenant_id=tenant_id), "started_at", window).order_by("started_at", "pk")
    return result("Till PIN-session cohorts by start time and stored lifecycle. No token/hash exported; these records evidence PIN sessions only, not HQ JWT assurance, password MFA or a certification of authentication security.",
        ["Session ID", "Started at", "Last seen", "Expires at", "Ended at", "End reason", "Device ID", "Location ID"],
        [[r.pk, r.started_at, r.last_seen_at, r.expires_at, r.ended_at, r.end_reason, r.device_id, r.location_id] for r in _bounded(qs)])
