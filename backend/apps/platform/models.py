from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimestampedModel


class PosRelease(TimestampedModel):
    """A downloadable POS installer.

    Deliberately not tenant scoped. An installer is the same binary for every
    pharmacy, and scoping it per tenant would mean uploading the same 35 MB
    artefact once per customer.

    The row is metadata only. The artefact itself lives in object storage and is
    handed out as a short-lived signed URL, so the binary never passes through
    the application server and a link cannot be forwarded indefinitely.
    """

    class Platform(models.TextChoices):
        WINDOWS = "WINDOWS", "Windows"
        ANDROID = "ANDROID", "Android"

    platform = models.CharField(max_length=16, choices=Platform.choices)
    #: Marketing version, e.g. "0.1.0-alpha.1". Matches the app's package.json.
    version = models.CharField(max_length=40)
    #: Monotonic per platform. Sorting on `version` would put 0.10.0 before 0.9.0.
    build_number = models.PositiveIntegerField()
    #: Key within the bucket, never a full URL: the bucket and endpoint are
    #: deployment configuration, and baking them into rows makes the data
    #: unmovable between environments.
    object_key = models.CharField(max_length=500)
    size_bytes = models.PositiveBigIntegerField()
    #: Lets an operator verify the download completed intact before installing.
    #: Published alongside the link for that reason.
    sha256 = models.CharField(max_length=64)
    release_notes = models.TextField(blank=True)
    #: Minimum OS the build runs on, shown so somebody does not download an
    #: installer their till cannot run.
    minimum_os = models.CharField(max_length=80, blank=True)
    #: Clients reporting a build below this must upgrade before POS operations
    #: that affect stock, cash or clinical decisions continue. Zero means the
    #: release is advisory only — Sync Centre still surfaces it daily.
    minimum_supported_build = models.PositiveIntegerField(default=0)
    #: Operator-facing note for HQ upgrades that change till behaviour
    #: (screening rules, dispensing gates, cash controls, etc.).
    operations_impact = models.TextField(blank=True)
    #: Unpublished rows are invisible to the API. Uploading an artefact and
    #: releasing it are separate acts.
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "version"], name="uq_posrelease_platform_version"
            ),
            models.UniqueConstraint(
                fields=["platform", "build_number"], name="uq_posrelease_platform_build"
            ),
        ]
        indexes = [
            models.Index(fields=["platform", "-build_number"], name="ix_posrelease_latest"),
        ]
        ordering = ["platform", "-build_number"]

    def __str__(self) -> str:
        return f"{self.get_platform_display()} {self.version}"

    def clean(self):
        super().clean()
        errors = {}
        # A checksum that is not a SHA-256 cannot verify anything, and a wrong
        # one is worse than none: it invites an operator to "verify" and pass.
        digest = (self.sha256 or "").strip().lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            errors["sha256"] = "Must be a 64-character hexadecimal SHA-256 digest."
        if self.size_bytes is not None and self.size_bytes <= 0:
            errors["size_bytes"] = "An installer cannot be zero bytes."
        if not (self.object_key or "").strip():
            errors["object_key"] = "An object key is required."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.sha256:
            self.sha256 = self.sha256.strip().lower()
        return super().save(*args, **kwargs)


# Demo scenario ownership models live in apps/platform/demo/models.py for
# cohesion, but Django only discovers <app>/models.py -- importing them here
# registers them under the `platform` app label.
from apps.platform.demo.models import (  # noqa: E402,F401  (re-export for discovery)
    DemoScenarioObject,
    DemoScenarioRun,
    DemoSeedApproval,
)
