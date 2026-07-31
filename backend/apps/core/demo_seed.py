"""Fail-closed safety policy for demo seed management commands.

Demo seeders create privileged accounts -- pharmacists, CDS approvers, HQ
operators -- and are useful precisely because they need no arguments. That
combination is dangerous against a live database, so the policy here is
deliberately fail-closed: a command refuses unless it can prove it is not
running against production.

Two independent gates:

  * Environment. ``settings.DAWATRACE_ENV`` is the canonical setting (see
    dawatrace/settings/base.py). If it resolves to a production-like value the
    command always refuses, and no flag overrides that.
  * Intent. Outside DEBUG the operator must pass ``--allow-demo-seed``, so a
    staging run is a deliberate act rather than a stray invocation.

Passwords are never literals in this file or its callers. They come from an
environment variable, or -- under DEBUG only -- are generated randomly and
shown once.
"""

from __future__ import annotations

import os
import secrets
import string

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError

#: Environment values that must never run a demo seeder, whatever flags are
#: passed. Compared case-insensitively after stripping surrounding whitespace.
PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod", "live"})

#: Environment variable each demo seeder reads its password from.
DEMO_PASSWORD_ENV_VAR = "DAWATRACE_DEMO_SEED_PASSWORD"

_GENERATED_PASSWORD_LENGTH = 24


def resolved_environment() -> str:
    """The canonical deployment environment, normalised for comparison."""

    return str(getattr(settings, "DAWATRACE_ENV", "") or "").strip().lower()


def is_production_environment() -> bool:
    return resolved_environment() in PRODUCTION_ENVIRONMENTS


def add_demo_seed_arguments(parser) -> None:
    """Register the shared ``--allow-demo-seed`` flag on a command parser."""

    parser.add_argument(
        "--allow-demo-seed",
        action="store_true",
        default=False,
        help=(
            "Confirm this is not a production database. Required outside DEBUG. "
            "Never sufficient when DAWATRACE_ENV is production, prod or live."
        ),
    )


def ensure_demo_seed_allowed(*, allow_demo_seed: bool) -> None:
    """Refuse unless this is demonstrably a non-production database.

    Raises CommandError -- which Django reports as a clean failure rather than
    a traceback -- when the environment is production-like, or when neither
    DEBUG nor an explicit flag establishes intent.
    """

    environment = resolved_environment()
    if environment in PRODUCTION_ENVIRONMENTS:
        raise CommandError(
            f"Refusing to run a demo seeder: DAWATRACE_ENV is {environment!r}. "
            "This command creates privileged accounts and is never permitted "
            "against production. --allow-demo-seed does not override this."
        )

    if settings.DEBUG:
        return

    if not allow_demo_seed:
        raise CommandError(
            "Refusing to run a demo seeder outside DEBUG without --allow-demo-seed. "
            f"Resolved DAWATRACE_ENV is {environment or 'unset'!r}. Pass "
            "--allow-demo-seed only when you are certain this is not a live database."
        )


def generate_demo_password() -> str:
    """A random password for local development, strong enough for validators."""

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_"
    return "".join(secrets.choice(alphabet) for _ in range(_GENERATED_PASSWORD_LENGTH))


def resolve_demo_password(*, allow_generated_fallback: bool = False) -> tuple[str, bool]:
    """Return ``(password, was_generated)`` for a demo seeder.

    Prefers ``DAWATRACE_DEMO_SEED_PASSWORD``, which lets the operator choose and
    record the credential. Falls back to a random value under DEBUG, or when the
    caller has already established non-production intent via ``--allow-demo-seed``.

    A generated password is never printed outside DEBUG, so accounts seeded that
    way on staging cannot be logged into by guessing -- which is why the fallback
    is safe. With neither signal present an absent variable is a hard failure.
    """

    supplied = os.environ.get(DEMO_PASSWORD_ENV_VAR, "").strip()
    if supplied:
        try:
            validate_password(supplied)
        except ValidationError as exc:
            raise CommandError(
                f"{DEMO_PASSWORD_ENV_VAR} failed password validation: "
                + "; ".join(exc.messages)
            ) from exc
        return supplied, False

    if settings.DEBUG or allow_generated_fallback:
        return generate_demo_password(), True

    raise CommandError(
        f"{DEMO_PASSWORD_ENV_VAR} must be set when DEBUG is False and "
        "--allow-demo-seed was not passed. Demo seeders never fall back to a "
        "fixed password."
    )


def demo_password_notice(password: str, *, was_generated: bool) -> str:
    """A summary line describing the credential without leaking it.

    The password itself is returned only when it was generated under DEBUG --
    a value the operator has no other way to learn. A supplied password is
    never echoed: whoever set the variable already knows it.
    """

    if not was_generated:
        return f"Password: supplied via {DEMO_PASSWORD_ENV_VAR} (not shown)."

    if settings.DEBUG:
        return (
            "Password: generated for LOCAL DEVELOPMENT ONLY -- shown once, not stored.\n"
            f"  {password}"
        )

    return "Password: generated (not shown outside DEBUG)."
