from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.cds.models import ClinicalKnowledgeRelease
from apps.clinical.models import ClinicalCondition, ClinicalEncounter, ClinicalObservation
from apps.crosswalks.models import LegacyIdentifierCrosswalk
from apps.customers.models import Customer
from apps.documents.models import StoredClinicalDocument
from apps.fhir.models import FHIRIdempotencyRecord
from apps.identity.models import User
from apps.inventory.models import InventoryBatch
from apps.medicines.models import (
    ActiveSubstance,
    ClinicalMedicinalProduct,
    CommercialSKU,
    Manufacturer,
)
from apps.notifications.models import NotificationOutbox
from apps.organizations.models import Location
from apps.patients.models import Patient
from apps.pos_shift.models import RegisterSession
from apps.practitioners.models import Practitioner
from apps.prescription.models import ClinicalSubstitution, DispensingLabel, Prescription
from apps.pricing.models import PriceBook
from apps.procurement.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseRequisition,
    ReceivedBatch,
)
from apps.sales.models import (
    DeliveryRecord,
    DispatchOrder,
    Quotation,
    SalesOrder,
    SalesReturnAuthorization,
)
from apps.tenancy.models import Tenant
from apps.terminology.models import FHIRCodeSystemRegistration, FHIRValueSetRegistration
from apps.workflows.models import DomainEvent


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
    purchase_orders = _scope(PurchaseOrder.all_objects, tenant_id)
    customers = _scope(Customer.all_objects, tenant_id)
    skus = _scope(CommercialSKU.all_objects, tenant_id)
    sales_orders = _scope(SalesOrder.all_objects, tenant_id)
    price_books = _scope(PriceBook.all_objects, tenant_id)
    open_register_sessions = _scope(
        RegisterSession.all_objects.filter(state="OPEN"),
        tenant_id,
    )

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
    open_purchase_orders = purchase_orders.filter(
        status__in={
            PurchaseOrder.Status.APPROVED,
            PurchaseOrder.Status.SENT,
            PurchaseOrder.Status.PARTIALLY_RECEIVED,
        }
    ).count()
    open_sales_orders = sales_orders.exclude(
        status__in={"CANCELLED", "CLOSED", "COMPLETED", "DELIVERED", "FULFILLED"}
    ).count()
    catalogue_skus = skus.count()
    customer_count = customers.count()
    price_book_count = price_books.count()
    open_tills = open_register_sessions.count()
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
            "href": "#network",
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
            "href": "#network",
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
            "href": "#network",
        }

    metrics = [
        primary_metric,
        {
            "label": "Patients",
            "value": patients.count(),
            "detail": "Registered care records",
            "accent": "teal",
            "href": "#people/patients",
        },
        {
            "label": "Open prescriptions",
            "value": open_prescriptions,
            "detail": "Not at a final outcome",
            "accent": "amber",
            "href": "#clinical",
        },
        {
            "label": "Released stock batches",
            "value": inventory_batches.filter(
                quality_status=InventoryBatch.QualityStatus.RELEASED
            ).count(),
            "detail": "Ready for use",
            "accent": "violet",
            "href": "#inventory",
        },
    ]
    attention_items = [
        {
            "label": "Prescription workflow",
            "value": open_prescriptions,
            "detail": "Items remain in an active dispensing or review state.",
            "tone": "amber",
            "href": "#clinical",
        },
        {
            "label": "Inventory quality holds",
            "value": quality_holds,
            "detail": "Batches need quality release, review, or disposition.",
            "tone": "rose",
            "href": "#inventory",
        },
        {
            "label": "Open sales orders",
            "value": open_sales_orders,
            "detail": "Customer orders still progressing through fulfilment.",
            "tone": "amber",
            "href": "#commerce/orders",
        },
        {
            "label": "Tills still trading",
            "value": open_tills,
            "detail": "Open register sessions that need cash oversight.",
            "tone": "amber" if open_tills else "teal",
            "href": "#cash/sessions",
        },
        {
            "label": "Clinical knowledge releases",
            "value": active_releases,
            "detail": "Active releases are available to clinical decision support.",
            "tone": "teal",
            "href": "#clinical",
        },
        {
            "label": "Open purchase orders",
            "value": open_purchase_orders,
            "detail": "Approved or sent orders still need receiving work.",
            "tone": "amber",
            "href": "#operations",
        },
    ]
    data_summary = [
        {"label": "Active locations", "value": active_locations, "href": "#network"},
        {"label": "Active users", "value": active_users, "href": "#access"},
        {"label": "Patients", "value": patients.count(), "href": "#people/patients"},
        {"label": "Practitioners", "value": practitioners.count(), "href": "#people/practitioners"},
        {"label": "Customers", "value": customer_count, "href": "#people/customers"},
        {"label": "Commercial SKUs", "value": catalogue_skus, "href": "#catalogue/skus"},
        {"label": "Clinical encounters", "value": encounters.count(), "href": "#clinical"},
        {"label": "Conditions", "value": conditions.count(), "href": "#clinical"},
        {"label": "Observations", "value": observations.count(), "href": "#clinical"},
        {"label": "Inventory batches", "value": inventory_batches.count(), "href": "#inventory"},
        {"label": "Open purchase orders", "value": open_purchase_orders, "href": "#operations"},
        {"label": "Open sales orders", "value": open_sales_orders, "href": "#commerce/orders"},
        {"label": "Price books", "value": price_book_count, "href": "#pricing/books"},
        {"label": "Open tills", "value": open_tills, "href": "#cash/tills"},
        {"label": "Active clinical releases", "value": active_releases, "href": "#clinical"},
        {"label": "Code systems", "value": code_systems.count(), "href": "#clinical"},
        {"label": "Value sets", "value": value_sets.count(), "href": "#clinical"},
        {"label": "FHIR idempotency records", "value": fhir_idempotency_records.count(), "href": "#clinical"},
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


def build_hq_workspace_context(tenant_id):
    patients = _scope(Patient.all_objects, tenant_id)
    practitioners = _scope(Practitioner.all_objects, tenant_id)
    customers = _scope(Customer.all_objects, tenant_id)
    skus = _scope(CommercialSKU.all_objects, tenant_id)
    substances = _catalog_scope(ActiveSubstance.all_objects, tenant_id)
    manufacturers = _catalog_scope(Manufacturer.all_objects, tenant_id)
    quotations = _scope(Quotation.all_objects, tenant_id)
    orders = _scope(SalesOrder.all_objects, tenant_id)
    dispatches = _scope(DispatchOrder.all_objects, tenant_id)
    deliveries = _scope(DeliveryRecord.all_objects, tenant_id)
    returns = _scope(SalesReturnAuthorization.all_objects, tenant_id)
    audit_events = _scope(AuditEvent.all_objects, tenant_id)
    documents = _scope(StoredClinicalDocument.all_objects, tenant_id)
    domain_events = _scope(DomainEvent.all_objects, tenant_id)
    notifications = _scope(NotificationOutbox.all_objects, tenant_id)
    crosswalks = _scope(LegacyIdentifierCrosswalk.all_objects, tenant_id)
    encounters = _scope(ClinicalEncounter.all_objects, tenant_id)
    conditions = _scope(ClinicalCondition.all_objects, tenant_id)
    observations = _scope(ClinicalObservation.all_objects, tenant_id)
    clinical_releases = _catalog_scope(ClinicalKnowledgeRelease.all_objects, tenant_id)
    code_systems = _catalog_scope(FHIRCodeSystemRegistration.all_objects, tenant_id)
    value_sets = _catalog_scope(FHIRValueSetRegistration.all_objects, tenant_id)
    substitutions = _scope(ClinicalSubstitution.all_objects, tenant_id)
    dispensing_labels = _scope(DispensingLabel.all_objects, tenant_id)
    fhir_idempotency = _scope(FHIRIdempotencyRecord.all_objects, tenant_id)

    open_order_statuses = {
        "DRAFT",
        "PENDING_APPROVAL",
        "APPROVED",
        "CONFIRMED",
        "ON_HOLD",
        "ALLOCATING",
        "ALLOCATED",
        "PICKING",
        "PICKED",
        "PACKING",
        "PACKED",
        "PARTIALLY_DISPATCHED",
        "DISPATCHED",
        "PARTIALLY_DELIVERED",
    }

    return {
        "generated_at": timezone.now().isoformat(),
        "business_modules": _build_business_modules(tenant_id),
        "people": {
            "counts": {
                "patients": patients.count(),
                "active_patients": patients.filter(is_active=True).count(),
                "practitioners": practitioners.count(),
                "verified_practitioners": practitioners.filter(
                    verification_state="VERIFIED"
                ).count(),
                "customers": customers.count(),
                "active_customers": customers.filter(status="ACTIVE").count(),
            },
            "patients": [
                {
                    "id": str(patient.id),
                    "patient_number": patient.patient_number
                    or patient.internal_reference_id,
                    "full_name": patient.full_name or "Unnamed patient",
                    "verification_status": patient.verification_status,
                    "consent_status": patient.consent_status,
                    "is_active": patient.is_active,
                    "updated_at": patient.updated_at,
                }
                for patient in patients.order_by("-updated_at")[:20]
            ],
            "practitioners": [
                {
                    "id": str(practitioner.id),
                    "full_name": practitioner.full_name,
                    "profession": practitioner.profession,
                    "registration_number": practitioner.registration_number,
                    "licence_status": practitioner.licence_status,
                    "verification_state": practitioner.verification_state,
                    "status": practitioner.status,
                }
                for practitioner in practitioners.order_by("-updated_at")[:20]
            ],
            "customers": list(
                customers.order_by("-updated_at")
                .values(
                    "id",
                    "customer_number",
                    "legal_name",
                    "customer_type",
                    "status",
                    "risk_classification",
                    "credit_status",
                )[:20]
            ),
        },
        "catalogue": {
            "counts": {
                "skus": skus.count(),
                "active_skus": skus.filter(status="ACTIVE").count(),
                "substances": substances.count(),
                "manufacturers": manufacturers.count(),
            },
            "skus": [
                {
                    "id": str(sku.id),
                    "sku_code": sku.sku_code,
                    "display_name": sku.display_name,
                    "brand_name": sku.manufactured_product.brand_name,
                    "canonical_medicine_name": (
                        sku.manufactured_product.clinical_product.canonical_name
                    ),
                    "default_barcode": sku.default_barcode,
                    "status": sku.status,
                    "is_saleable": sku.is_saleable,
                    "is_purchasable": sku.is_purchasable,
                    "is_dispensable": sku.is_dispensable,
                }
                for sku in skus.select_related(
                    "manufactured_product__clinical_product"
                ).order_by("display_name")[:30]
            ],
        },
        "commerce": {
            "counts": {
                "quotations": quotations.count(),
                "orders": orders.count(),
                "open_orders": orders.filter(status__in=open_order_statuses).count(),
                "dispatches": dispatches.count(),
                "deliveries": deliveries.count(),
                "returns": returns.count(),
            },
            "orders": [
                {
                    "id": str(order.id),
                    "order_number": order.order_number,
                    "customer_name": order.customer.legal_name,
                    "currency": order.currency,
                    "total": str(order.total),
                    "status": order.status,
                    "priority": order.priority,
                    "order_date": order.order_date,
                    "requested_delivery_date": order.requested_delivery_date,
                }
                for order in orders.select_related("customer").order_by("-created_at")[:20]
            ],
            "dispatches": [
                {
                    "id": str(dispatch.id),
                    "dispatch_number": dispatch.dispatch_number,
                    "customer_name": dispatch.customer.legal_name,
                    "carrier": dispatch.carrier,
                    "status": dispatch.status,
                    "dispatch_date": dispatch.dispatch_date,
                    "expected_delivery_date": dispatch.expected_delivery_date,
                }
                for dispatch in dispatches.select_related("customer").order_by(
                    "-created_at"
                )[:20]
            ],
        },
        # Clinical decision support, terminology and encounters had no surface at
        # all: the workspace carried counts for code systems and value sets, and
        # the UI offered cards that linked back to the page they were on. These
        # are the rows behind those counts.
        #
        # They come through the aggregate rather than the per-app collections
        # because those are capability-gated and tenant-filtered, so a platform
        # administrator -- who has no tenant -- gets a 403 from them and an empty
        # list past it. _scope returns every tenant's rows when no tenant is
        # selected, which is what "All tenants" means in the scope picker.
        "clinical": {
            "counts": {
                "encounters": encounters.count(),
                "conditions": conditions.count(),
                "observations": observations.count(),
                "knowledge_releases": clinical_releases.count(),
                "active_knowledge_releases": clinical_releases.filter(is_active=True).count(),
                "code_systems": code_systems.count(),
                "value_sets": value_sets.count(),
                "fhir_idempotency_records": fhir_idempotency.count(),
                "substitutions": substitutions.count(),
                "dispensing_labels": dispensing_labels.count(),
            },
            "knowledge_releases": [
                {
                    "id": str(release.id),
                    "code": release.code,
                    "version": release.version,
                    "source": release.source,
                    "source_version": release.source_version,
                    "licence": release.licence,
                    "effective_date": release.effective_date,
                    "expires_at": release.expires_at,
                    "is_active": release.is_active,
                    "classification": release.content_classification,
                    # Truncated for list view; full digest available for particulars.
                    "checksum": (release.checksum_sha256 or "")[:12],
                    "checksum_full": release.checksum_sha256 or "",
                }
                for release in clinical_releases.order_by("-effective_date")[:50]
            ],
            "code_systems": [
                {
                    "id": str(system.id),
                    "name": system.name,
                    "title": system.title,
                    "url": system.url,
                    "version": system.version.version if system.version_id else "",
                    "content_mode": system.content_mode,
                    "is_global": system.is_global,
                    "concept_count": len(system.concepts_json or []),
                    "sample_concepts": [
                        {
                            "code": str(concept.get("code") or ""),
                            "display": str(concept.get("display") or concept.get("code") or ""),
                        }
                        for concept in (system.concepts_json or [])[:8]
                        if isinstance(concept, dict)
                    ],
                }
                for system in code_systems.select_related("version").order_by("name")[:50]
            ],
            "value_sets": [
                {
                    "id": str(value_set.id),
                    "name": value_set.name,
                    "title": value_set.title,
                    "url": value_set.url,
                    "version": value_set.version.version if value_set.version_id else "",
                    "is_global": value_set.is_global,
                    "compose": value_set.compose_json or {},
                }
                for value_set in value_sets.select_related("version").order_by("name")[:50]
            ],
            "encounters": [
                {
                    "id": str(encounter.id),
                    "patient_name": (
                        " ".join(
                            p for p in (encounter.patient.first_name, encounter.patient.last_name) if p
                        ).strip()
                        or encounter.patient.patient_number
                    )
                    if encounter.patient
                    else None,
                    "patient_number": encounter.patient.patient_number if encounter.patient else "",
                    "status": encounter.status,
                    "encounter_class": encounter.encounter_class,
                    "practitioner_name": (
                        (encounter.practitioner.professional_name or "").strip()
                        or " ".join(
                            p
                            for p in (
                                encounter.practitioner.first_name,
                                encounter.practitioner.last_name,
                            )
                            if p
                        ).strip()
                    )
                    if encounter.practitioner
                    else None,
                    "organization_name": encounter.organization.name if encounter.organization else "",
                    "location_name": encounter.location.name if encounter.location else "",
                    "start_time": encounter.start_time,
                    "end_time": encounter.end_time,
                    "reason_code": encounter.reason_code or "",
                }
                for encounter in encounters.select_related(
                    "patient", "practitioner", "organization", "location"
                ).order_by("-start_time")[:50]
            ],
            "conditions": [
                {
                    "id": str(condition.id),
                    "patient_name": (
                        " ".join(
                            p for p in (condition.patient.first_name, condition.patient.last_name) if p
                        ).strip()
                        or condition.patient.patient_number
                    )
                    if condition.patient
                    else None,
                    "clinical_status": condition.clinical_status,
                    "verification_status": condition.verification_status,
                    "category": condition.category or "",
                    "code": condition.code,
                    "system": condition.system or "",
                    "display": condition.display or condition.code,
                    "onset_date": condition.onset_date,
                    "recorded_date": condition.recorded_date,
                    "encounter_id": str(condition.encounter_id) if condition.encounter_id else "",
                }
                for condition in conditions.select_related("patient", "encounter").order_by(
                    "-recorded_date"
                )[:50]
            ],
            "observations": [
                {
                    "id": str(observation.id),
                    "patient_name": (
                        " ".join(
                            p
                            for p in (observation.patient.first_name, observation.patient.last_name)
                            if p
                        ).strip()
                        or observation.patient.patient_number
                    )
                    if observation.patient
                    else None,
                    "status": observation.status,
                    "category": observation.category or "",
                    "code": observation.code,
                    "system": observation.system or "",
                    "display": observation.display or observation.code,
                    "effective_time": observation.effective_time,
                    "value_quantity": (
                        str(observation.value_quantity) if observation.value_quantity is not None else ""
                    ),
                    "value_unit": observation.value_unit or "",
                    "value_string": observation.value_string or "",
                    "interpretation": observation.interpretation or "",
                    "encounter_id": str(observation.encounter_id) if observation.encounter_id else "",
                }
                for observation in observations.select_related("patient", "encounter").order_by(
                    "-effective_time", "-id"
                )[:50]
            ],
            "fhir_idempotency_records": [
                {
                    "id": str(record.id),
                    "key": record.key,
                    "resource_type": record.resource_type,
                    "operation": record.operation,
                    "resource_id": str(record.resource_id) if record.resource_id else "",
                    "state": record.state,
                    "response_status": record.response_status,
                    "request_hash": (record.request_hash or "")[:16],
                    "request_hash_full": record.request_hash or "",
                    "actor": record.actor.username if record.actor else "System",
                    "created_at": record.created_at,
                }
                for record in fhir_idempotency.select_related("actor").order_by("-created_at")[:50]
            ],
        },
        "governance": {
            "counts": {
                "audit_events": audit_events.count(),
                "documents": documents.count(),
                "domain_events": domain_events.count(),
                "failed_domain_events": domain_events.filter(status="FAILED").count(),
                "notifications": notifications.count(),
                "pending_notifications": notifications.filter(status="PENDING").count(),
                "crosswalks": crosswalks.count(),
            },
            "audit_events": [
                {
                    "id": str(event.id),
                    "actor": event.actor.username if event.actor else "System",
                    "action": event.action,
                    "model_name": event.model_name,
                    "object_id": event.object_id,
                    "outcome": event.outcome,
                    "correlation_id": event.correlation_id,
                    "created_at": event.created_at,
                }
                for event in audit_events.select_related("actor").order_by("-created_at")[
                    :25
                ]
            ],
            "documents": list(
                documents.order_by("-created_at")
                .values(
                    "id",
                    "original_name",
                    "content_type",
                    "size_bytes",
                    "malware_scan_status",
                    "created_at",
                )[:20]
            ),
            "domain_events": list(
                domain_events.order_by("-created_at")
                .values(
                    "id",
                    "aggregate_type",
                    "event_type",
                    "status",
                    "attempts",
                    "last_error",
                    "created_at",
                )[:20]
            ),
            "notifications": [
                {
                    "id": str(notification.id),
                    "channel": notification.channel,
                    "recipient": _mask_recipient(notification.recipient),
                    "template_code": notification.template_code,
                    "status": notification.status,
                    "last_error": notification.last_error,
                    "created_at": notification.created_at,
                }
                for notification in notifications.order_by("-created_at")[:20]
            ],
            "crosswalks": [
                {
                    "id": str(crosswalk.id),
                    "source_system": crosswalk.source_system.code,
                    "source_entity_type": crosswalk.source_entity_type,
                    "target_entity_type": crosswalk.target_entity_type,
                    "migration_batch": crosswalk.migration_batch,
                    "migrated_at": crosswalk.migrated_at,
                    "created_at": crosswalk.created_at,
                }
                for crosswalk in crosswalks.select_related("source_system").order_by(
                    "-created_at"
                )[:20]
            ],
        },
    }


def _scope(queryset, tenant_id):
    if tenant_id:
        return queryset.filter(tenant_id=tenant_id)
    return queryset


def _build_business_modules(tenant_id):
    customers = _scope(Customer.all_objects, tenant_id).select_related("tenant")
    practitioners = _scope(Practitioner.all_objects, tenant_id).select_related(
        "tenant"
    )
    patients = _scope(Patient.all_objects, tenant_id).select_related("tenant")
    products = _catalog_scope(
        ClinicalMedicinalProduct.all_objects, tenant_id
    ).select_related("tenant", "dose_form")
    requisitions = _scope(
        PurchaseRequisition.all_objects, tenant_id
    ).select_related("tenant", "requesting_branch", "requester")
    purchase_orders = _scope(PurchaseOrder.all_objects, tenant_id).select_related(
        "tenant", "supplier", "ordering_branch"
    )
    receipts = _scope(GoodsReceipt.all_objects, tenant_id).select_related(
        "tenant", "supplier", "receiving_branch"
    )
    received_batches = _scope(
        ReceivedBatch.all_objects, tenant_id
    ).select_related("tenant", "sku")
    quotations = _scope(Quotation.all_objects, tenant_id).select_related(
        "tenant", "customer"
    )
    sales_orders = (
        _scope(SalesOrder.all_objects, tenant_id)
        .select_related("tenant", "customer")
        .prefetch_related("holds")
    )
    dispatches = _scope(DispatchOrder.all_objects, tenant_id).select_related(
        "tenant", "customer"
    ).prefetch_related("lines")
    sales_returns = (
        _scope(SalesReturnAuthorization.all_objects, tenant_id)
        .select_related("tenant", "customer")
        .prefetch_related("lines__sku")
    )
    prescriptions = _scope(Prescription.all_objects, tenant_id).select_related(
        "tenant", "patient", "practitioner"
    )
    users = _scope(User.objects, tenant_id).select_related("tenant")

    return [
        {
            "key": "patients",
            "domain": "people",
            "title": "Patient registry",
            "description": "Identity-safe patient registration and consent posture.",
            "records": [
                _work_item(
                    patient,
                    reference=patient.patient_number
                    or patient.internal_reference_id,
                    title=patient.full_name or "Unnamed patient",
                    status=patient.verification_status,
                    detail=f"Consent: {patient.consent_status}",
                    metrics=[
                        {"label": "Active", "value": "Yes" if patient.is_active else "No"},
                        {"label": "Updated", "value": patient.updated_at.isoformat()},
                    ],
                )
                for patient in patients.order_by("-updated_at")[:50]
            ],
        },
        {
            "key": "practitioners",
            "domain": "people",
            "title": "Practitioner governance",
            "description": "Professional identity, licence and prescribing verification.",
            "records": [
                _work_item(
                    practitioner,
                    reference=practitioner.registration_number or "Unregistered",
                    title=practitioner.full_name,
                    status=practitioner.verification_state,
                    detail=practitioner.get_profession_display(),
                    metrics=[
                        {"label": "Licence", "value": practitioner.licence_status},
                        {
                            "label": "Controlled medicines",
                            "value": (
                                "Authorised"
                                if practitioner.controlled_medicine_authority
                                else "Not authorised"
                            ),
                        },
                    ],
                    actions=(
                        [
                            _business_action(
                                "verify-practitioner",
                                "Verify practitioner",
                                f"/api/practitioners/{practitioner.id}/verify/",
                                fields=[
                                    _action_field(
                                        "verification_state",
                                        "Verification decision",
                                        "select",
                                        default="VERIFIED",
                                        options=[
                                            "VERIFIED",
                                            "MANUAL_REVIEW",
                                            "REJECTED",
                                        ],
                                    ),
                                    _action_field(
                                        "licence_status",
                                        "Licence status",
                                        default=practitioner.licence_status,
                                    ),
                                    _action_field(
                                        "controlled_medicine_authority",
                                        "Controlled medicine authority",
                                        "checkbox",
                                        default=practitioner.controlled_medicine_authority,
                                    ),
                                ],
                                confirm=(
                                    "This decision changes prescribing authority "
                                    "and is recorded against your account."
                                ),
                            )
                        ]
                        if practitioner.verification_state != "VERIFIED"
                        else []
                    ),
                )
                for practitioner in practitioners.order_by("-updated_at")[:50]
            ],
        },
        {
            "key": "customers",
            "domain": "people",
            "title": "Customer governance",
            "description": "Commercial approval, risk and credit eligibility.",
            "records": [
                _work_item(
                    customer,
                    reference=customer.customer_number,
                    title=customer.legal_name,
                    status=customer.status,
                    detail=customer.get_customer_type_display(),
                    metrics=[
                        {"label": "Risk", "value": customer.risk_classification},
                        {"label": "Credit", "value": customer.credit_status},
                    ],
                    actions=_customer_actions(customer),
                )
                for customer in customers.order_by("-updated_at")[:50]
            ],
        },
        {
            "key": "clinical-products",
            "domain": "catalogue",
            "title": "Clinical products",
            "description": "Canonical medicines moving through catalogue governance.",
            "records": [
                _work_item(
                    product,
                    reference=product.code,
                    title=product.canonical_name,
                    status=product.status,
                    detail=product.dose_form.name if product.dose_form_id else "No dose form",
                    metrics=[
                        {
                            "label": "Prescription class",
                            "value": product.prescription_classification,
                        },
                        {
                            "label": "Controlled class",
                            "value": product.controlled_classification or "None",
                        },
                    ],
                    actions=(
                        [
                            _business_action(
                                "activate-product",
                                "Activate product",
                                f"/api/medicines/clinical-products/{product.id}/activate/",
                                confirm=(
                                    "Activation makes this clinical product available "
                                    "to downstream catalogue workflows."
                                ),
                            )
                        ]
                        if product.status != "ACTIVE"
                        else []
                    ),
                )
                for product in products.order_by("canonical_name")[:50]
            ],
        },
        {
            "key": "requisitions",
            "domain": "operations",
            "title": "Purchase requisitions",
            "description": "Internal replenishment demand awaiting procurement decisions.",
            "records": [
                _work_item(
                    requisition,
                    reference=requisition.requisition_number,
                    title=requisition.requesting_branch.name,
                    status=requisition.status,
                    detail=requisition.justification or "No justification supplied",
                    metrics=[
                        {"label": "Priority", "value": requisition.priority},
                        {
                            "label": "Needed by",
                            "value": requisition.requested_delivery_date.isoformat(),
                        },
                    ],
                    actions=_requisition_actions(requisition),
                )
                for requisition in requisitions.order_by("-created_at")[:50]
            ],
        },
        {
            "key": "purchase-orders",
            "domain": "operations",
            "title": "Purchase orders",
            "description": "Supplier commitments from approval through transmission.",
            "records": [
                _work_item(
                    order,
                    reference=order.po_number,
                    title=order.supplier.legal_name,
                    status=order.status,
                    detail=order.ordering_branch.name,
                    metrics=[
                        {
                            "label": "Gross",
                            "value": f"{order.currency} {order.total_gross}",
                        },
                        {
                            "label": "Expected",
                            "value": order.expected_delivery_date.isoformat(),
                        },
                    ],
                    actions=_purchase_order_actions(order),
                )
                for order in purchase_orders.order_by("-created_at")[:50]
            ],
        },
        {
            "key": "goods-receipts",
            "domain": "operations",
            "title": "Goods receiving",
            "description": "Delivery capture, discrepancy review and receipt closure.",
            "records": [
                _work_item(
                    receipt,
                    reference=receipt.grn_number,
                    title=receipt.supplier.legal_name,
                    status=receipt.status,
                    detail=receipt.receiving_branch.name,
                    metrics=[
                        {
                            "label": "Arrival",
                            "value": receipt.arrival_time.isoformat(),
                        },
                        {
                            "label": "Discrepancy",
                            "value": receipt.discrepancy_summary or "None",
                        },
                    ],
                    actions=(
                        [
                            _business_action(
                                "close-receipt",
                                "Close goods receipt",
                                f"/api/procurement/goods-receipts/{receipt.id}/close/",
                                confirm=(
                                    "Closing freezes receipt totals and prevents further "
                                    "delivery capture."
                                ),
                            )
                        ]
                        if receipt.status
                        in {"RECEIVED", "PARTIALLY_ACCEPTED", "ACCEPTED"}
                        else []
                    ),
                )
                for receipt in receipts.order_by("-created_at")[:50]
            ],
        },
        {
            "key": "received-batches",
            "domain": "operations",
            "title": "Batch quality release",
            "description": "Inspection outcomes before received stock becomes available.",
            "records": [
                _work_item(
                    batch,
                    reference=batch.manufacturer_batch_number,
                    title=batch.sku.display_name,
                    status=batch.quality_status,
                    detail=f"Expires {batch.expiry_date.isoformat()}",
                    metrics=[
                        {"label": "Received", "value": str(batch.received_quantity)},
                        {
                            "label": "Temperature excursion",
                            "value": "Yes" if batch.temperature_excursion else "No",
                        },
                    ],
                    actions=(
                        [
                            _business_action(
                                "release-batch",
                                "Release batch",
                                f"/api/procurement/received-batches/{batch.id}/release/",
                                fields=[
                                    _action_field(
                                        "reason",
                                        "Release justification",
                                        "textarea",
                                        required=True,
                                    )
                                ],
                                confirm=(
                                    "Released stock can be reserved, sold and dispensed."
                                ),
                            )
                        ]
                        if batch.quality_status
                        in {"PENDING_INSPECTION", "QUARANTINED"}
                        else []
                    ),
                )
                for batch in received_batches.order_by("-created_at")[:50]
            ],
        },
        {
            "key": "quotations",
            "domain": "commerce",
            "title": "Quotations",
            "description": "Commercial offers moving from draft to accepted demand.",
            "records": [
                _work_item(
                    quotation,
                    reference=quotation.quotation_number,
                    title=quotation.customer.legal_name,
                    status=quotation.status,
                    detail=(
                        f"Valid until {quotation.valid_until.isoformat()}"
                        if quotation.valid_until
                        else "No expiry date set"
                    ),
                    metrics=[
                        {
                            "label": "Total",
                            "value": f"{quotation.currency} {quotation.total}",
                        },
                        {"label": "Revision", "value": str(quotation.revision)},
                    ],
                    actions=_quotation_actions(quotation),
                )
                for quotation in quotations.order_by("-created_at")[:50]
            ],
        },
        {
            "key": "sales-orders",
            "domain": "commerce",
            "title": "Sales orders",
            "description": "Order approval, reservation, allocation and exception control.",
            "records": [
                _work_item(
                    order,
                    reference=order.order_number,
                    title=order.customer.legal_name,
                    status=order.status,
                    detail=f"Priority {order.priority}" if order.priority else "Standard priority",
                    metrics=[
                        {"label": "Total", "value": f"{order.currency} {order.total}"},
                        {
                            "label": "Delivery",
                            "value": (
                                order.requested_delivery_date.isoformat()
                                if order.requested_delivery_date
                                else "Not scheduled"
                            ),
                        },
                    ],
                    actions=_sales_order_actions(order),
                )
                for order in sales_orders.order_by("-created_at")[:50]
            ],
        },
        {
            "key": "dispatches",
            "domain": "commerce",
            "title": "Dispatch control",
            "description": "Outbound approval and release to the delivery network.",
            "records": [
                _work_item(
                    dispatch,
                    reference=dispatch.dispatch_number,
                    title=dispatch.customer.legal_name,
                    status=dispatch.status,
                    detail=dispatch.carrier or "Internal fleet",
                    metrics=[
                        {
                            "label": "Dispatch date",
                            "value": (
                                dispatch.dispatch_date.isoformat()
                                if dispatch.dispatch_date
                                else "Not scheduled"
                            ),
                        },
                        {
                            "label": "Expected",
                            "value": (
                                dispatch.expected_delivery_date.isoformat()
                                if dispatch.expected_delivery_date
                                else "Not scheduled"
                            ),
                        },
                    ],
                    actions=_dispatch_actions(dispatch),
                )
                for dispatch in dispatches.order_by("-created_at")[:50]
            ],
        },
        {
            "key": "sales-returns",
            "domain": "commerce",
            "title": "Sales returns",
            "description": "Return authorisation and controlled receipt.",
            "records": [
                _work_item(
                    sales_return,
                    reference=sales_return.return_number,
                    title=sales_return.customer.legal_name,
                    status=sales_return.status,
                    detail=sales_return.reason,
                    metrics=[],
                    actions=_sales_return_actions(sales_return),
                )
                for sales_return in sales_returns.order_by("-created_at")[:50]
            ],
        },
        {
            "key": "prescriptions",
            "domain": "clinical",
            "title": "Prescription safety workflow",
            "description": "Legal validation, clinical review and pharmacist verification.",
            "records": [
                _work_item(
                    prescription,
                    reference=prescription.prescription_number,
                    title=prescription.patient.full_name,
                    status=prescription.status,
                    detail=f"Prescriber: {prescription.practitioner.full_name}",
                    metrics=[
                        {
                            "label": "Legal",
                            "value": prescription.legal_validation_state,
                        },
                        {
                            "label": "Clinical",
                            "value": prescription.clinical_review_state,
                        },
                        {
                            "label": "Verification",
                            "value": prescription.pharmacist_verification_state,
                        },
                    ],
                    actions=_prescription_actions(prescription),
                )
                for prescription in prescriptions.order_by("-created_at")[:50]
            ],
        },
        {
            "key": "users",
            "domain": "access",
            "title": "User access register",
            "description": "Account status and workspace assignment.",
            "records": [
                _work_item(
                    user,
                    reference=user.username,
                    title=user.get_full_name() or user.username,
                    status="ACTIVE" if user.is_active else "INACTIVE",
                    detail=(
                        "Platform administrator"
                        if user.is_platform_admin or user.is_superuser
                        else "Tenant user"
                    ),
                    metrics=[
                        {
                            "label": "Workspace",
                            "value": user.tenant.name if user.tenant_id else "Platform",
                        },
                        {
                            "label": "Last login",
                            "value": (
                                user.last_login.isoformat()
                                if user.last_login
                                else "Never"
                            ),
                        },
                    ],
                )
                for user in users.order_by("username")[:100]
            ],
        },
    ]


def _work_item(
    instance,
    *,
    reference,
    title,
    status,
    detail,
    metrics,
    actions=None,
):
    return {
        "id": str(instance.id),
        "tenant_id": str(instance.tenant_id) if instance.tenant_id else "",
        "tenant_name": instance.tenant.name if instance.tenant_id else "Platform",
        "reference": reference,
        "title": title,
        "status": status,
        "detail": detail,
        "metrics": metrics,
        "actions": actions or [],
    }


def _business_action(key, label, path, *, fields=None, confirm="", tone="primary"):
    return {
        "key": key,
        "label": label,
        "path": path,
        "method": "POST",
        "fields": fields or [],
        "confirm": confirm,
        "tone": tone,
    }


def _action_field(
    name,
    label,
    field_type="text",
    *,
    required=False,
    default="",
    options=None,
):
    return {
        "name": name,
        "label": label,
        "type": field_type,
        "required": required,
        "default": default,
        "options": options or [],
    }


def _customer_actions(customer):
    if customer.status == "PROSPECTIVE":
        return [
            _business_action(
                "begin-customer-review",
                "Begin customer review",
                f"/api/customers/customers/{customer.id}/begin-review/",
                fields=[
                    _action_field(
                        "reason",
                        "Review initiation note",
                        "textarea",
                        required=True,
                    )
                ],
                confirm="Move this prospective customer into formal governance review.",
            )
        ]
    if customer.status == "UNDER_REVIEW":
        return [
            _business_action(
                "approve-customer",
                "Approve customer",
                f"/api/customers/customers/{customer.id}/approve/",
                fields=[
                    _action_field(
                        "reason",
                        "Approval note",
                        "textarea",
                        required=True,
                    )
                ],
                confirm="Approval confirms governance review; activation is a separate decision.",
            )
        ]
    if customer.status == "APPROVED":
        return [
            _business_action(
                "activate-customer",
                "Activate customer",
                f"/api/customers/customers/{customer.id}/activate/",
                fields=[
                    _action_field(
                        "reason",
                        "Activation note",
                        "textarea",
                        required=True,
                    )
                ],
                confirm="Activation enables this approved customer to pass active commercial policy checks.",
            )
        ]
    if customer.status == "ACTIVE":
        return [
            _business_action(
                "suspend-customer",
                "Suspend customer",
                f"/api/customers/customers/{customer.id}/suspend/",
                fields=[
                    _action_field(
                        "reason",
                        "Suspension reason",
                        "textarea",
                        required=True,
                    )
                ],
                confirm=(
                    "Suspension blocks new commercial transactions until reviewed."
                ),
                tone="danger",
            )
        ]
    if customer.status == "SUSPENDED":
        return [
            _business_action(
                "reactivate-customer",
                "Reactivate customer",
                f"/api/customers/customers/{customer.id}/reactivate/",
                fields=[
                    _action_field(
                        "reason",
                        "Reactivation reason",
                        "textarea",
                        required=True,
                    )
                ],
                confirm="Reactivation restores this customer to active commercial policy checks.",
            )
        ]
    return []


def _purchase_order_actions(order):
    if order.status == "DRAFT":
        return [
            _business_action(
                "approve-purchase-order",
                "Approve purchase order",
                f"/api/procurement/purchase-orders/{order.id}/approve/",
                confirm="Approval creates an authorised supplier commitment.",
            )
        ]
    if order.status == "APPROVED":
        return [
            _business_action(
                "send-purchase-order",
                "Send to supplier",
                f"/api/procurement/purchase-orders/{order.id}/send/",
                confirm="This records the purchase order as transmitted to the supplier.",
            )
        ]
    return []


def _requisition_actions(requisition):
    if requisition.status == "DRAFT":
        return [
            _business_action(
                "submit-requisition",
                "Submit requisition",
                f"/api/procurement/requisitions/{requisition.id}/submit/",
                confirm=(
                    "Submission freezes the draft for approval and starts the "
                    "segregated procurement review."
                ),
            )
        ]
    if requisition.status in {"SUBMITTED", "UNDER_REVIEW"}:
        return [
            _business_action(
                "approve-requisition",
                "Approve requisition",
                f"/api/procurement/requisitions/{requisition.id}/approve/",
                confirm=(
                    "Approval authorises procurement to commit against this "
                    "internal demand."
                ),
            )
        ]
    return []


def _quotation_actions(quotation):
    transitions = {
        "DRAFT": ("submit", "Submit quotation"),
        "SUBMITTED": ("approve", "Approve quotation"),
        "APPROVED": ("send", "Send quotation"),
        "SENT": ("accept", "Record acceptance"),
        "ACCEPTED": ("convert", "Convert to order"),
    }
    transition = transitions.get(quotation.status)
    if not transition:
        return []
    action, label = transition
    return [
        _business_action(
            f"{action}-quotation",
            label,
            f"/api/sales/quotations/{quotation.id}/{action}/",
            confirm=f"{label} and advance this commercial workflow?",
        )
    ]


def _sales_order_actions(order):
    if order.status == "ON_HOLD":
        actions = [
            _business_action(
                f"release-sales-order-hold-{hold.id}",
                f"Release {hold.get_hold_type_display()} hold",
                f"/api/sales/orders/{order.id}/release_hold/",
                fields=[
                    _action_field(
                        "hold_id",
                        "Hold",
                        "hidden",
                        required=True,
                        default=str(hold.id),
                    ),
                    _action_field(
                        "release_reason",
                        "Release reason",
                        "textarea",
                        required=True,
                    ),
                ],
                confirm=(
                    "Release this hold only after its commercial or compliance "
                    "cause has been resolved."
                ),
            )
            for hold in order.holds.all()
            if hold.is_active
        ]
        actions.append(
            _business_action(
                "cancel-sales-order",
                "Cancel order",
                f"/api/sales/orders/{order.id}/cancel/",
                fields=[
                    _action_field(
                        "reason",
                        "Cancellation reason",
                        "textarea",
                        required=True,
                    )
                ],
                confirm="Cancellation is a final commercial outcome.",
                tone="danger",
            )
        )
        return actions

    transitions = {
        "DRAFT": ("submit", "Submit order"),
        "SUBMITTED": ("approve", "Approve order"),
        "APPROVED": ("reserve", "Reserve inventory"),
        "RESERVED": ("allocate", "Allocate stock"),
        "PARTIALLY_ALLOCATED": ("allocate", "Continue allocation"),
    }
    actions = []
    transition = transitions.get(order.status)
    if transition:
        action, label = transition
        actions.append(
            _business_action(
                f"{action}-sales-order",
                label,
                f"/api/sales/orders/{order.id}/{action}/",
                confirm=f"{label} and advance this order?",
            )
        )
    if order.status not in {"CANCELLED", "CLOSED", "DELIVERED", "REJECTED"}:
        actions.append(
            _business_action(
                "hold-sales-order",
                "Place hold",
                f"/api/sales/orders/{order.id}/hold/",
                fields=[
                    _action_field(
                        "hold_type",
                        "Hold type",
                        "select",
                        required=True,
                        default="MANUAL_REVIEW",
                        options=[
                            "CREDIT",
                            "COMPLIANCE",
                            "CUSTOMER",
                            "PRICING",
                            "INVENTORY",
                            "QUALITY",
                            "RECALL",
                            "DELIVERY",
                            "MANUAL_REVIEW",
                        ],
                    ),
                    _action_field(
                        "reason",
                        "Hold reason",
                        "textarea",
                        required=True,
                    ),
                ],
                confirm="A hold prevents the order from progressing.",
                tone="warning",
            )
        )
        actions.append(
            _business_action(
                "cancel-sales-order",
                "Cancel order",
                f"/api/sales/orders/{order.id}/cancel/",
                fields=[
                    _action_field(
                        "reason",
                        "Cancellation reason",
                        "textarea",
                        required=True,
                    )
                ],
                confirm="Cancellation is a final commercial outcome.",
                tone="danger",
            )
        )
    return actions


def _dispatch_actions(dispatch):
    if dispatch.status in {"DRAFT", "READY"}:
        return [
            _business_action(
                "approve-dispatch",
                "Approve dispatch",
                f"/api/sales/dispatches/{dispatch.id}/approve/",
                confirm="Approve this outbound dispatch?",
            )
        ]
    if dispatch.status == "APPROVED":
        return [
            _business_action(
                "load-dispatch",
                "Confirm loading",
                f"/api/sales/dispatches/{dispatch.id}/load/",
                confirm=(
                    "Confirm that every sealed package assigned to this dispatch "
                    "is physically loaded."
                ),
            )
        ]
    if dispatch.status == "LOADED":
        return [
            _business_action(
                "release-dispatch",
                "Release dispatch",
                f"/api/sales/dispatches/{dispatch.id}/dispatch/",
                confirm="Release the loaded dispatch to the carrier?",
            )
        ]
    return []


def _sales_return_actions(sales_return):
    if sales_return.status == "UNDER_REVIEW":
        return [
            _business_action(
                "approve-return",
                "Approve return",
                f"/api/sales/returns/{sales_return.id}/approve/",
                confirm=(
                    "Approval authorises the customer to return the recorded "
                    "products."
                ),
            )
        ]
    if sales_return.status in {"APPROVED", "AWAITING_RETURN"}:
        fields = [
            _action_field(
                f"received_quantities.{line.id}",
                f"{line.sku.display_name} received (authorised {line.quantity})",
                "number",
                required=True,
                default="0",
            )
            for line in sales_return.lines.all()
        ]
        return [
            _business_action(
                "receive-return",
                "Receive return",
                f"/api/sales/returns/{sales_return.id}/receive/",
                fields=fields,
                confirm=(
                    "Record only quantities physically received into return "
                    "custody. Quality disposition remains a separate control."
                ),
            )
        ]
    return []


def _prescription_actions(prescription):
    actions = []
    if (
        prescription.legal_validation_state != "PASSED"
        and prescription.status in {"DRAFT", "RECEIVED", "INTAKE_REVIEW"}
    ):
        actions.append(
            _business_action(
                "validate-prescription",
                "Run legal validation",
                f"/api/prescriptions/{prescription.id}/validate/",
                confirm="Run legal validation against the current prescription record?",
            )
        )
    if (
        prescription.legal_validation_state == "PASSED"
        and prescription.clinical_review_state != "COMPLETED"
        and prescription.status in {"LEGALLY_VALIDATED", "CLINICAL_REVIEW"}
    ):
        actions.append(
            _business_action(
                "clinical-review-prescription",
                "Complete clinical review",
                f"/api/prescriptions/{prescription.id}/clinical-review/",
                fields=[
                    _action_field(
                        "outcome",
                        "Review outcome",
                        "select",
                        required=True,
                        default="APPROVED",
                        options=["APPROVED", "INTERVENTION_REQUIRED", "REJECTED"],
                    ),
                    _action_field("notes", "Clinical notes", "textarea"),
                ],
                confirm="Complete the pharmacist clinical review?",
            )
        )
    if (
        prescription.clinical_review_state == "COMPLETED"
        and prescription.pharmacist_verification_state != "VERIFIED"
        and prescription.status
        in {"LEGALLY_VALIDATED", "CLINICAL_REVIEW", "INTERVENTION_REQUIRED"}
    ):
        actions.append(
            _business_action(
                "verify-prescription",
                "Verify prescription",
                f"/api/prescriptions/{prescription.id}/verify/",
                fields=[
                    _action_field(
                        "decision",
                        "Verification decision",
                        "select",
                        required=True,
                        default="VERIFIED",
                        options=["VERIFIED", "REJECTED"],
                    ),
                    _action_field(
                        "clinical_justification",
                        "Clinical justification",
                        "textarea",
                    ),
                ],
                confirm="Record pharmacist verification?",
            )
        )
    if prescription.status == "ON_HOLD":
        actions.append(
            _business_action(
                "release-prescription-hold",
                "Release hold",
                f"/api/prescriptions/{prescription.id}/release-hold/",
                fields=[
                    _action_field(
                        "reason",
                        "Release reason",
                        "textarea",
                        required=True,
                    )
                ],
                confirm="Release this clinical hold?",
            )
        )
    elif prescription.status not in {
        "CANCELLED",
        "CLOSED",
        "COMPLETED",
        "EXPIRED",
        "REJECTED",
        "SUPPLIED",
    }:
        actions.append(
            _business_action(
                "hold-prescription",
                "Place clinical hold",
                f"/api/prescriptions/{prescription.id}/hold/",
                fields=[
                    _action_field(
                        "reason",
                        "Hold reason",
                        "textarea",
                        required=True,
                    )
                ],
                confirm="A clinical hold prevents dispensing until resolved.",
                tone="warning",
            )
        )
    return actions


def _catalog_scope(queryset, tenant_id):
    if tenant_id:
        return queryset.filter(Q(tenant_id=tenant_id) | Q(is_global=True))
    return queryset


def _mask_recipient(recipient):
    if "@" in recipient:
        local, domain = recipient.split("@", 1)
        return f"{local[:2]}***@{domain}"
    if len(recipient) > 4:
        return f"***{recipient[-4:]}"
    return "***"
