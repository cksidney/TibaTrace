"""Deterministic synthetic identities.

Two rules govern everything here.

**Determinism.** Every value derives from the run seed and a stable key, never
from `random` module state, iteration order or the clock. The generator calls
`rng_for(seed, "patients", 7)` rather than drawing from one shared stream, so
adding a stage -- or reordering two -- does not shift every value that follows.
A shared stream would make the manifest digest depend on execution order, and
the digest is what an approval binds to.

**Nothing may resemble a real person or a real identifier.** The data is
fictional, and it must also be *provably* fictional on inspection:

* Phone numbers use +254 700 000 000-999999, which is not an allocated
  Safaricom/Airtel subscriber range in the form used here, and every number is
  prefixed identically so a block is obvious.
* Email lands on `demo.invalid` -- `.invalid` is reserved by RFC 2606 and can
  never be registered or delivered to.
* Patient identifiers use the `NCD-` prefix and are *not* Kenyan national ID
  format (8 digits). An 8-digit string here could be mistaken for a real ID,
  so the format deliberately cannot be parsed as one.
* Names are drawn from a fixed pool of common Kenyan given names and surnames
  and combined by seed. A collision with a real person's name is unavoidable in
  any naming scheme; what matters is that no record is *derived* from a real
  person, and that every record is marked demo-owned.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta

#: RFC 2606 reserved TLD: unregistrable, undeliverable.
DEMO_EMAIL_DOMAIN = "nairobichemists.demo.invalid"

#: Prefix for every synthetic phone number in the scenario.
DEMO_PHONE_PREFIX = "+254700"

#: Patient identifier prefix. Deliberately not parseable as a Kenyan national
#: ID (8 digits) or a passport number.
PATIENT_IDENTIFIER_PREFIX = "NCD"

#: Truth labels. The engine never contacts an external registry, so anything it
#: records about verification says so.
TRUTH_MANUAL = "MANUAL_INTERNAL_VERIFICATION"
TRUTH_SANDBOX = "SANDBOX_EVIDENCE_ONLY"
TRUTH_NOT_CONNECTED = "NOT_EXTERNALLY_CONNECTED"

GIVEN_NAMES = (
    "Achieng", "Amina", "Anyango", "Brian", "Caroline", "Cynthia", "Daniel",
    "David", "Esther", "Faith", "Fatuma", "Geoffrey", "Grace", "Hassan",
    "Irene", "James", "Janet", "Joseph", "Joyce", "Kevin", "Lilian", "Mercy",
    "Michael", "Mwangi", "Nancy", "Nasra", "Otieno", "Patrick", "Peter",
    "Rachel", "Rose", "Samuel", "Sarah", "Stephen", "Susan", "Teresa",
    "Vincent", "Wanjiru", "Winnie", "Zipporah",
)

SURNAMES = (
    "Achieng", "Barasa", "Chebet", "Gitau", "Hassan", "Kamau", "Karanja",
    "Kimani", "Kiptoo", "Kirui", "Koech", "Maina", "Mbugua", "Mohamed",
    "Mutiso", "Mwangi", "Njeri", "Njoroge", "Nyambura", "Ochieng", "Odhiambo",
    "Okello", "Omondi", "Onyango", "Otieno", "Wafula", "Wanjala", "Wanjiku",
    "Waweru", "Yusuf",
)

#: Nairobi sub-areas. Used for a *synthetic* address label only -- never a
#: street address, which could name a real premises.
NAIROBI_AREAS = (
    "Central Business District", "Westlands", "Kilimani", "Lavington",
    "Parklands", "South B", "South C", "Embakasi", "Kasarani", "Langata",
)

CHRONIC_CONDITIONS = (
    "Type 2 diabetes mellitus", "Essential hypertension", "Asthma",
    "Chronic kidney disease", "Hypothyroidism", "Epilepsy",
    "Rheumatoid arthritis", "Congestive cardiac failure",
)

ALLERGIES = (
    "Penicillin", "Sulfonamides", "Aspirin", "Codeine", "Latex",
    "Iodinated contrast", "Peanut", "Shellfish",
)


def stable_int(seed: int, *parts: object) -> int:
    """A stable integer from the seed and a key.

    SHA-256 rather than `hash()`, which is salted per process and would make
    the same plan produce different data on every run.
    """
    key = "|".join([str(seed), *(str(p) for p in parts)])
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


def rng_for(seed: int, *parts: object) -> random.Random:
    """An independent RNG stream for one key.

    Independent per key on purpose: a single shared stream makes every value
    depend on how many draws happened before it, so inserting one supplier
    would change every patient generated afterwards -- and with it the manifest
    digest, and with it a previously granted approval.

    Bandit flags `random` as unsuitable for security use, and is right in
    general -- but reproducibility is the entire requirement here, and a
    cryptographic generator cannot be reproduced from a seed. Nothing this
    produces is a secret: passwords come from the guarded demo-password
    mechanism, never from this module.
    """
    return random.Random(stable_int(seed, *parts))  # noqa: S311 - deterministic by design


def pick(seed: int, choices, *parts: object):
    """Deterministically choose one item from an ordered sequence."""
    ordered = tuple(choices)
    if not ordered:
        raise ValueError("Cannot pick from an empty sequence.")
    return ordered[stable_int(seed, *parts) % len(ordered)]


def person_name(seed: int, *parts: object) -> tuple[str, str]:
    """A synthetic given name and surname."""
    return (
        pick(seed, GIVEN_NAMES, "given", *parts),
        pick(seed, SURNAMES, "surname", *parts),
    )


def phone_number(seed: int, *parts: object) -> str:
    """A synthetic phone number in a single obvious block."""
    return f"{DEMO_PHONE_PREFIX}{stable_int(seed, 'phone', *parts) % 1_000_000:06d}"


def email_address(local_part: str) -> str:
    """An undeliverable address on a reserved TLD."""
    cleaned = "".join(ch for ch in local_part.lower() if ch.isalnum() or ch in "._-")
    return f"{cleaned}@{DEMO_EMAIL_DOMAIN}"


def patient_identifier(seed: int, index: int) -> str:
    """A synthetic patient identifier that cannot be read as a national ID.

    Kenyan national IDs are eight digits. This is prefixed and eleven
    characters of mixed content, so it fails that shape on inspection as well
    as by policy.
    """
    body = stable_int(seed, "patient-identifier", index) % 10_000_000
    return f"{PATIENT_IDENTIFIER_PREFIX}-{body:07d}"


def birth_date(seed: int, index: int, *, as_of: date, min_age: int, max_age: int) -> date:
    """A birth date placing the person in an age band, deterministically."""
    if min_age > max_age:
        raise ValueError("min_age cannot exceed max_age")
    span_days = max(1, (max_age - min_age) * 365)
    offset = stable_int(seed, "dob", index) % span_days
    return as_of - timedelta(days=min_age * 365 + offset)


# ---------------------------------------------------------------------------
# GS1
# ---------------------------------------------------------------------------

#: GS1 prefix 952 is documented by GS1 as a *demonstration/internal* prefix and
#: is not issued to a member company, so identifiers built on it cannot collide
#: with a real product's GTIN. Using a Kenyan member prefix (616) would create
#: identifiers that look allocated and could collide.
GS1_DEMO_PREFIX = "952"


def gtin13_check_digit(body12: str) -> int:
    """Standard GS1 mod-10 check digit over the first twelve digits."""
    if len(body12) != 12 or not body12.isdigit():
        raise ValueError("A GTIN-13 body must be exactly twelve digits.")
    total = 0
    for position, char in enumerate(body12):
        # GS1 weights right-to-left as 3,1,3,1...; over a fixed 12-digit body
        # that is 1,3,1,3... left-to-right.
        total += int(char) * (1 if position % 2 == 0 else 3)
    return (10 - (total % 10)) % 10


def synthetic_gtin13(seed: int, *parts: object) -> str:
    """A check-digit-valid GTIN-13 in the demonstration prefix."""
    body = f"{GS1_DEMO_PREFIX}{stable_int(seed, 'gtin', *parts) % 1_000_000_000:09d}"
    return f"{body}{gtin13_check_digit(body)}"


def is_synthetic_gtin(value: str) -> bool:
    """Whether a GTIN was minted by this engine."""
    return bool(value) and value.startswith(GS1_DEMO_PREFIX) and len(value) == 13
