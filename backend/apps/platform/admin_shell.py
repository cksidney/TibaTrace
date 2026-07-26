from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from apps.cds.models import ClinicalKnowledgeRelease
from apps.clinical.models import ClinicalCondition, ClinicalEncounter, ClinicalObservation
from apps.fhir.models import FHIRIdempotencyRecord
from apps.identity.models import User
from apps.inventory.models import InventoryBatch
from apps.organizations.models import Location
from apps.patients.models import Patient
from apps.practitioners.models import Practitioner
from apps.prescription.models import Prescription
from apps.tenancy.models import Tenant
from apps.terminology.models import FHIRCodeSystemRegistration, FHIRValueSetRegistration


@login_required
def admin_shell(request):
    tenant_id = getattr(request, "tenant_id", None) or request.user.tenant_id
    return render(
        request,
        "platform/admin_shell.html",
        build_hq_dashboard_context(request.user, tenant_id),
    )


def build_hq_dashboard_context(user, tenant_id):
    is_platform_overview = not tenant_id and (
        user.is_superuser or user.is_platform_admin
    )

    patients = _scope(Patient.all_objects, tenant_id)
    practitioners = _scope(Practitioner.all_objects, tenant_id)
    prescriptions = _scope(Prescription.all_objects, tenant_id)
    encounters = _scope(ClinicalEncounter.all_objects, tenant_id)
    conditions = _scope(ClinicalCondition.all_objects, tenant_id)
    observations = _scope(ClinicalObservation.all_objects, tenant_id)
    clinical_releases = _scope(ClinicalKnowledgeRelease.all_objects, tenant_id)
    code_systems = _scope(FHIRCodeSystemRegistration.all_objects, tenant_id)
    value_sets = _scope(FHIRValueSetRegistration.all_objects, tenant_id)
    fhir_idempotency_records = _scope(FHIRIdempotencyRecord.all_objects, tenant_id)
    locations = _scope(Location.all_objects, tenant_id)
    inventory_batches = _scope(InventoryBatch.all_objects, tenant_id)

    final_prescription_statuses = {
        "CANCELLED",
        "CLOSED",
        "COMPLETED",
        "EXPIRED",
        "REJECTED",
        "SUPPLIED",
    }
    open_prescriptions = prescriptions.exclude(status__in=final_prescription_statuses).count()
    quality_holds = inventory_batches.exclude(quality_status=InventoryBatch.QualityStatus.RELEASED).count()
    active_releases = clinical_releases.filter(is_active=True).count()
    active_locations = locations.filter(status="ACTIVE").count()
    active_users = _scope(User.objects.filter(is_active=True), tenant_id).count()
    network_tenants = Tenant.objects.all()
    if tenant_id:
        network_tenants = network_tenants.filter(id=tenant_id)
    network_items = list(
        network_tenants.annotate(
            active_location_count=Count(
                "healthcare_locations",
                filter=Q(healthcare_locations__status="ACTIVE"),
                distinct=True,
            ),
            active_patient_count=Count(
                "patients",
                filter=Q(patients__is_active=True),
                distinct=True,
            ),
            active_practitioner_count=Count(
                "practitioners",
                filter=Q(practitioners__status="ACTIVE"),
                distinct=True,
            ),
            active_user_count=Count(
                "users",
                filter=Q(users__is_active=True),
                distinct=True,
            ),
        )
        .values(
            "id",
            "name",
            "slug",
            "status",
            "country_code",
            "time_zone",
            "active_location_count",
            "active_patient_count",
            "active_practitioner_count",
            "active_user_count",
        )
        .order_by("name")[:100]
    )
    for item in network_items:
        item["id"] = str(item["id"])

    if is_platform_overview:
        scope_label = "Platform overview"
        scope_description = "A consolidated view across every TibaTrace tenant."
        tenant_name = "All tenants"
        primary_metric = {
            "label": "Active tenants",
            "value": Tenant.objects.filter(status=Tenant.STATUS_ACTIVE).count(),
            "detail": "Live workspaces",
            "accent": "navy",
        }
    elif tenant_id:
        tenant = Tenant.objects.filter(id=tenant_id).only("name").first()
        tenant_name = tenant.name if tenant else "Selected tenant"
        scope_label = "Tenant overview"
        scope_description = "Operational activity for the selected TibaTrace workspace."
        primary_metric = {
            "label": "Active locations",
            "value": active_locations,
            "detail": "Operating care sites",
            "accent": "navy",
        }
    else:
        tenant_name = "No workspace selected"
        scope_label = "Workspace required"
        scope_description = "Select a tenant workspace to view operational data."
        primary_metric = {
            "label": "Active tenants",
            "value": Tenant.objects.filter(status=Tenant.STATUS_ACTIVE).count(),
            "detail": "Available workspaces",
            "accent": "navy",
        }

    metrics = [
        primary_metric,
        {
            "label": "Patients",
            "value": patients.count(),
            "detail": "Registered care records",
            "accent": "teal",
        },
        {
            "label": "Open prescriptions",
            "value": open_prescriptions,
            "detail": "Not at a final outcome",
            "accent": "amber",
        },
        {
            "label": "Released stock batches",
            "value": inventory_batches.filter(
                quality_status=InventoryBatch.QualityStatus.RELEASED
            ).count(),
            "detail": "Ready for use",
            "accent": "violet",
        },
    ]
    attention_items = [
        {
            "label": "Prescription workflow",
            "value": open_prescriptions,
            "detail": "Items remain in an active dispensing or review state.",
            "tone": "amber",
        },
        {
            "label": "Inventory quality holds",
            "value": quality_holds,
            "detail": "Batches need quality release, review, or disposition.",
            "tone": "rose",
        },
        {
            "label": "Clinical knowledge releases",
            "value": active_releases,
            "detail": "Active releases are available to clinical decision support.",
            "tone": "teal",
        },
    ]
    data_summary = [
        {"label": "Active locations", "value": active_locations},
        {"label": "Active users", "value": active_users},
        {"label": "Practitioners", "value": practitioners.count()},
        {"label": "Clinical encounters", "value": encounters.count()},
        {"label": "Conditions", "value": conditions.count()},
        {"label": "Observations", "value": observations.count()},
        {"label": "Inventory batches", "value": inventory_batches.count()},
        {"label": "Active clinical releases", "value": active_releases},
        {"label": "Code systems", "value": code_systems.count()},
        {"label": "Value sets", "value": value_sets.count()},
        {"label": "FHIR idempotency records", "value": fhir_idempotency_records.count()},
    ]

    return {
        "attention_items": attention_items,
        "data_summary": data_summary,
        "generated_at": timezone.now().isoformat(),
        "is_platform_overview": is_platform_overview,
        "metrics": metrics,
        "network_items": network_items,
        "scope_description": scope_description,
        "scope_label": scope_label,
        "tenant_id": str(tenant_id) if tenant_id else "",
        "tenant_name": tenant_name,
        "user_name": user.get_full_name() or user.username,
    }


def _scope(queryset, tenant_id):
    if tenant_id:
        return queryset.filter(tenant_id=tenant_id)
    return queryset
