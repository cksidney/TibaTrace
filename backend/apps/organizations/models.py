from django.db import models

from apps.core.models import StrictTenantManager, TenantConsistencyMixin, TimestampedModel


class Organization(TimestampedModel):
    TYPE_PHARMACY = "PHARMACY"
    TYPE_HOSPITAL = "HOSPITAL"
    TYPE_CLINIC = "CLINIC"
    TYPE_CHOICES = (
        (TYPE_PHARMACY, "Pharmacy"),
        (TYPE_HOSPITAL, "Hospital"),
        (TYPE_CLINIC, "Clinic"),
        ("OTHER", "Other"),
    )

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="healthcare_organizations")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=80)
    organization_type = models.CharField(max_length=40, choices=TYPE_CHOICES, default=TYPE_PHARMACY)
    status = models.CharField(max_length=20, default="ACTIVE")
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uq_org_tenant_code")]
        indexes = [models.Index(fields=["tenant", "status", "name"], name="ix_org_tenant_status")]


class OrganizationIdentifier(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("organization",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="identifiers")
    system = models.CharField(max_length=255)
    value = models.CharField(max_length=255)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "system", "value"], name="uq_org_identifier_tenant")
        ]


class Location(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("organization",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="healthcare_locations")
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="locations")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=80)
    location_type = models.CharField(max_length=50, default="PHARMACY")
    status = models.CharField(max_length=20, default="ACTIVE")
    address = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "code"], name="uq_location_tenant_code")]
        indexes = [models.Index(fields=["tenant", "organization", "status"], name="ix_location_tenant_org")]


class Department(TenantConsistencyMixin, TimestampedModel):
    """An operating unit within a site: the dispensary, the stores, the till.

    A department is an *organisational* grouping and nothing more. It carries no
    capabilities, and `User.effective_capabilities` does not consult it --
    permission comes from `identity.Role` alone. Two independent paths to a
    capability would mean no single place answers "what can this person do?",
    and the answer to that question gates controlled-drug access.

    What a department is for: knowing who works where, and slicing reports by
    unit. Where it does touch authorisation, it does so through the mechanism
    that already exists -- `identity.AttributePolicy` matches on `User.metadata`,
    and department membership is mirrored there under a stable key, so a policy
    can deny a capability outside its department without a new mechanism.

    Departments hang off a site rather than a tenant: the dispensary at the CBD
    branch and the dispensary at Westlands are separately staffed, separately
    stocked and separately reported.
    """

    TYPE_DISPENSARY = "DISPENSARY"
    TYPE_RETAIL = "RETAIL"
    TYPE_WHOLESALE = "WHOLESALE"
    TYPE_STORES = "STORES"
    TYPE_COLD_CHAIN = "COLD_CHAIN"
    TYPE_PROCUREMENT = "PROCUREMENT"
    TYPE_FINANCE = "FINANCE"
    TYPE_ADMINISTRATION = "ADMINISTRATION"
    TYPE_QUALITY = "QUALITY"
    TYPE_CLINICAL = "CLINICAL"
    TYPE_CHOICES = (
        (TYPE_DISPENSARY, "Dispensary"),
        (TYPE_RETAIL, "Retail Counter"),
        (TYPE_WHOLESALE, "Wholesale"),
        (TYPE_STORES, "Stores"),
        (TYPE_COLD_CHAIN, "Cold Chain"),
        (TYPE_PROCUREMENT, "Procurement"),
        (TYPE_FINANCE, "Finance"),
        (TYPE_ADMINISTRATION, "Administration"),
        (TYPE_QUALITY, "Quality Assurance"),
        (TYPE_CLINICAL, "Clinical Services"),
    )

    tenant_relation_fields = ("site",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    site = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="departments")
    code = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    department_type = models.CharField(max_length=40, choices=TYPE_CHOICES, default=TYPE_DISPENSARY)
    status = models.CharField(max_length=20, default="ACTIVE")
    metadata = models.JSONField(default=dict, blank=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "site", "code"], name="uq_department_tenant_site_code")
        ]
        indexes = [
            models.Index(fields=["tenant", "site", "status"], name="ix_department_tenant_site"),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.site_id})"


class DepartmentMembership(TenantConsistencyMixin, TimestampedModel):
    """Which department a member of staff works in.

    Deliberately shaped like `identity.UserRole` -- same tenant/user/is_active
    columns, same uniqueness -- because the two are read together and differing
    shapes invite the assumption that one implies the other. It does not: a role
    grants capabilities, a membership does not.

    A user may belong to several departments (a pharmacist covering both the
    dispensary and the retail counter); exactly one may be primary, which is the
    one mirrored into `User.metadata` for attribute policies.
    """

    tenant_relation_fields = ("department", "user")
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="memberships")
    user = models.ForeignKey(
        "identity.User", on_delete=models.CASCADE, related_name="department_memberships"
    )
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "department", "user"], name="uq_department_membership"
            ),
            # At most one primary department per user. Partial, so inactive and
            # non-primary rows are unconstrained.
            models.UniqueConstraint(
                fields=["tenant", "user"],
                condition=models.Q(is_primary=True, is_active=True),
                name="uq_department_primary_per_user",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "user", "is_active"], name="ix_dept_member_user"),
        ]


class LocationIdentifier(TenantConsistencyMixin, TimestampedModel):
    tenant_relation_fields = ("location",)
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="+")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="identifiers")
    system = models.CharField(max_length=255)
    value = models.CharField(max_length=255)

    objects = StrictTenantManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "system", "value"], name="uq_location_identifier_tenant")
        ]
