"""Supplier governance.

The rule this enforces: **a purchase order may only go to a supplier who is
allowed to receive one.**

That is not the same as a supplier who exists. A supplier row can be created in
seconds; being qualified to supply medicines means a current wholesale dealer
licence, current tax compliance, and — for controlled medicines or cold chain —
specific authorisations that expire. An expired licence is the normal case, not
the exotic one: they lapse annually and nobody notices until an inspector asks.

So `assert_can_receive_purchase_order` is the gate, it checks expiry against the
order date rather than against nothing, and it returns every reason a supplier
is ineligible rather than the first — a buyer told one problem at a time chases
one document at a time.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.procurement.models import Supplier, SupplierQualification


class SupplierNotQualified(ValidationError):
    """The supplier cannot receive this order."""


#: Qualifications every pharmaceutical supplier must hold, whatever they sell.
BASELINE_QUALIFICATIONS = frozenset(
    {
        SupplierQualification.QualificationType.BUSINESS_REGISTRATION,
        SupplierQualification.QualificationType.WHOLESALE_DEALER_LICENCE,
    }
)

#: Additional qualifications required by what is being bought.
CONTROLLED_QUALIFICATIONS = frozenset(
    {SupplierQualification.QualificationType.CONTROLLED_DRUG_LICENCE}
)
COLD_CHAIN_QUALIFICATIONS = frozenset(
    {SupplierQualification.QualificationType.COLD_CHAIN_AUTHORIZATION}
)

#: Statuses from which a supplier may be sent an order.
PURCHASABLE_STATUSES = frozenset({Supplier.Status.APPROVED, Supplier.Status.ACTIVE})


class SupplierGovernanceService:
    """Creates, approves and gates suppliers."""

    @staticmethod
    @transaction.atomic
    def create_supplier(*, tenant, supplier_code: str, legal_name: str, **fields) -> Supplier:
        """Register a supplier.

        Starts PROSPECTIVE. A newly typed supplier is a lead, not an approved
        counterparty, and creating one must not be a route to placing an order
        with it.
        """
        if not str(supplier_code or "").strip():
            raise ValidationError("A supplier requires a code.")
        if not str(legal_name or "").strip():
            raise ValidationError("A supplier requires a legal name.")

        existing = Supplier.all_objects.filter(
            tenant=tenant, supplier_code=supplier_code
        ).first()
        if existing is not None:
            return existing

        return Supplier.all_objects.create(
            tenant=tenant,
            supplier_code=supplier_code,
            legal_name=legal_name,
            status=Supplier.Status.PROSPECTIVE,
            **fields,
        )

    @staticmethod
    @transaction.atomic
    def approve_supplier(*, supplier: Supplier, approver, reason: str = "") -> Supplier:
        """Approve a supplier for purchasing.

        Requires a named approver. Approval is what turns a lead into a
        counterparty the organisation will pay, and it is not anonymous.
        """
        if approver is None:
            raise PermissionDenied("Supplier approval requires a named approver.")
        if supplier.status in {Supplier.Status.DISQUALIFIED, Supplier.Status.ARCHIVED}:
            raise ValidationError(
                f"A {supplier.status} supplier cannot be approved. "
                "Reinstate it explicitly first."
            )

        supplier.status = Supplier.Status.APPROVED
        # Record who approved and when. The check ran against this person; a
        # control that validates an approver and then discards them leaves no
        # evidence it ran, which is indistinguishable from never having run.
        supplier.approved_by = approver
        supplier.approved_at = timezone.now()
        supplier.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        return supplier

    @staticmethod
    @transaction.atomic
    def suspend_supplier(*, supplier: Supplier, reason: str, approver=None) -> Supplier:
        """Stop new orders without erasing history.

        Suspension does not touch existing orders or receipts. Goods already
        received were still received, and the invoices for them are still owed.

        An approver is recorded when there is one but is not required. This is
        the protective direction -- it stops purchasing -- and gating the safe
        action behind a second signature means a supplier stays orderable while
        somebody hunts for a manager. Approval, which permits purchasing, does
        require one.

        A reason is required either way: a suspension nobody can explain gets
        reversed by the next person who needs stock.
        """
        if not str(reason or "").strip():
            raise ValidationError("Supplier suspension requires a reason.")

        supplier.status = Supplier.Status.SUSPENDED
        # Persisted, not merely validated. The reason is what a buyer sees when
        # they find they cannot order, and what stops the suspension being
        # quietly reversed by whoever needs stock next.
        supplier.suspension_reason = reason
        supplier.save(update_fields=["status", "suspension_reason", "updated_at"])
        return supplier

    # ------------------------------------------------------------ eligibility

    @staticmethod
    def valid_qualifications(*, supplier: Supplier, on_date=None) -> set[str]:
        """Qualification types that are verified and current on the date.

        Expiry is checked against the order date, not against today. A licence
        that lapses next week was valid for an order placed today, and one that
        lapsed last month was not valid for a backdated order.
        """
        on_date = on_date or timezone.now().date()
        current = set()

        for qualification in SupplierQualification.all_objects.filter(supplier=supplier):
            if (
                qualification.verification_status
                != SupplierQualification.QualificationVerificationStatus.VERIFIED
            ):
                continue
            # Read the fields directly rather than through getattr with a
            # default. A defensive getattr here returned None for a misspelled
            # field name and silently skipped the expiry check altogether --
            # which fails open, and failing open is the one thing this gate
            # exists to prevent.
            if qualification.effective_date and on_date < qualification.effective_date:
                continue
            if qualification.expiry_date and on_date > qualification.expiry_date:
                continue
            current.add(qualification.qualification_type)
        return current

    @classmethod
    def ineligibility_reasons(cls, *, supplier: Supplier, on_date=None,
                              controlled: bool = False, cold_chain: bool = False) -> list[str]:
        """Every reason this supplier cannot be sent an order.

        All of them, not the first. A buyer told one problem at a time chases
        one document at a time, and the order slips a week per document.
        """
        reasons: list[str] = []

        if supplier.status not in PURCHASABLE_STATUSES:
            reasons.append(
                f"Supplier status is {supplier.status}; only "
                f"{' or '.join(sorted(PURCHASABLE_STATUSES))} may receive orders."
            )

        required = set(BASELINE_QUALIFICATIONS)
        if controlled:
            required |= CONTROLLED_QUALIFICATIONS
        if cold_chain:
            required |= COLD_CHAIN_QUALIFICATIONS

        held = cls.valid_qualifications(supplier=supplier, on_date=on_date)
        for missing in sorted(required - held):
            reasons.append(
                f"{missing} is missing, unverified or expired as at "
                f"{on_date or timezone.now().date()}."
            )
        return reasons

    @classmethod
    def can_receive_purchase_order(cls, *, supplier: Supplier, on_date=None,
                                   controlled: bool = False, cold_chain: bool = False) -> bool:
        return not cls.ineligibility_reasons(
            supplier=supplier, on_date=on_date, controlled=controlled, cold_chain=cold_chain
        )

    @classmethod
    def assert_can_receive_purchase_order(cls, *, supplier: Supplier, on_date=None,
                                          controlled: bool = False, cold_chain: bool = False) -> None:
        """The gate. Raises with every reason, or returns silently."""
        reasons = cls.ineligibility_reasons(
            supplier=supplier, on_date=on_date, controlled=controlled, cold_chain=cold_chain
        )
        if reasons:
            raise SupplierNotQualified(
                {
                    "supplier": [
                        f"{supplier.supplier_code} cannot receive a purchase order."
                    ]
                    + reasons
                }
            )
