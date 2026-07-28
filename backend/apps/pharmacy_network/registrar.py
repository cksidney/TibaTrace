"""Confirming a premises licence with the Pharmacy and Poisons Board.

There is no PPB API yet, so nothing here calls one. This module exists so that
the assumption is written down in one place instead of being spread across the
activation gate, and so that adding the integration is a matter of implementing
`verify_premises_licence` rather than finding everywhere a licence is trusted.

## What the rest of the module currently assumes

Every licence on file is MANUAL: somebody read a certificate and typed it in.
`PharmacyProfile.licence_is_current` therefore answers a narrow question -- is
there an unexpired licence recorded -- and deliberately not the question anyone
actually cares about, which is whether PPB still recognises it. PPB can revoke a
licence without our copy changing.

## What has to be decided when the API arrives

Two failure modes, and they should not get the same answer:

* **Activation** should fail closed. Refusing to make a new pharmacy live
  because the registrar cannot be reached is an inconvenience, and the
  alternative is putting a counter into service on an unchecked licence.

* **Continued trading** should fail open. Suspending working pharmacies because
  a government API had an outage would stop dispensing across the network for a
  reason that has nothing to do with any of them.

Recording that here because the two are easy to conflate while writing the
client, and getting the second one wrong is the kind of mistake that closes
pharmacies.
"""
from __future__ import annotations

from dataclasses import dataclass


class RegistrarUnavailable(RuntimeError):
    """The registrar could not be reached, or did not answer usefully.

    Distinct from "the registrar says this licence is invalid". Callers must
    treat the two differently -- see the module docstring.
    """


@dataclass(frozen=True)
class LicenceVerification:
    """What the registrar said about a premises licence."""

    licence_number: str
    is_recognised: bool
    expires_on: object | None
    superintendent_name: str
    #: The registrar's raw response, stored for audit. A compliance question
    #: asked in a year is about what PPB said, not about what we stored.
    raw: dict


def verify_premises_licence(licence_number: str) -> LicenceVerification:
    """Ask PPB about a licence.

    Not implemented: the API does not exist yet. It raises rather than returning
    a plausible-looking answer, because a stub that returns "recognised" would
    let an unlicensed pharmacy trade the moment somebody wired this in and
    forgot it was fiction.
    """
    raise NotImplementedError(
        "The PPB registrar integration is not built. Licence data is currently "
        "entered by hand and marked PharmacyProfile.LicenceSource.MANUAL."
    )
