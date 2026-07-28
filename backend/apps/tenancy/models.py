from django.db import models

from apps.core.models import TimestampedModel


class Tenant(TimestampedModel):
    """A pharmacy on the platform.

    The lifecycle lives here because `status` is the column every other app
    already points at, but the rules that move a tenant between these states --
    and the licence checks that gate them -- belong to `apps.pharmacy_network`.
    Nothing outside that module should assign `status` directly.
    """

    #: Signed or in discussion, nothing provisioned. Cannot sign in.
    STATUS_PROSPECT = "PROSPECT"
    #: Provisioned and being set up. Still cannot trade: a pharmacy mid-setup
    #: has no licence checked and no staff trained.
    STATUS_ONBOARDING = "ONBOARDING"
    #: Trading.
    STATUS_ACTIVE = "ACTIVE"
    #: Stopped, reversibly.
    STATUS_SUSPENDED = "SUSPENDED"
    #: Relationship ended. Terminal -- reactivation is a new tenant, so that the
    #: audit trail of the old one is never reopened and rewritten.
    STATUS_TERMINATED = "TERMINATED"

    STATUS_CHOICES = (
        (STATUS_PROSPECT, "Prospect"),
        (STATUS_ONBOARDING, "Onboarding"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_SUSPENDED, "Suspended"),
        (STATUS_TERMINATED, "Terminated"),
    )

    #: The states in which a tenant may use the platform at all. Read by the
    #: middleware, which is what gives suspension teeth.
    OPERATIONAL_STATUSES = frozenset({STATUS_ACTIVE})

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    country_code = models.CharField(max_length=2, default="KE")
    time_zone = models.CharField(max_length=64, default="Africa/Nairobi")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name", "id"]

    @property
    def is_active(self) -> bool:
        return self.status == self.STATUS_ACTIVE

    @property
    def may_operate(self) -> bool:
        """Whether requests for this tenant should be served.

        Distinct from `is_active` so the two can diverge later without silently
        changing what every caller of `is_active` means.
        """
        return self.status in self.OPERATIONAL_STATUSES

    def __str__(self) -> str:
        return self.name
