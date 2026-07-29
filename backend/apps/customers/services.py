from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.customers.models import Customer
from apps.workflows.service import emit_event


class CustomerGovernanceService:
    """Service for handling customer lifecycle transitions."""

    @staticmethod
    @transaction.atomic
    def create_customer(*, tenant, customer_number, legal_name, customer_type, created_by=None, **kwargs):
        status = kwargs.pop("status", Customer.Status.UNDER_REVIEW)
        customer = Customer.objects.create(
            tenant=tenant,
            customer_number=customer_number,
            legal_name=legal_name,
            customer_type=customer_type,
            status=status,
            created_by=created_by,
            **kwargs,
        )
        emit_event(
            tenant_id=tenant.id,
            aggregate_type="Customer",
            aggregate_id=customer.id,
            event_type="CustomerCreated",
            payload={"customer_number": customer.customer_number},
        )
        return customer

    @staticmethod
    @transaction.atomic
    def begin_review_customer(*, customer, actor=None, reason=""):
        if customer.status != Customer.Status.PROSPECTIVE:
            raise ValidationError("Customer must be PROSPECTIVE to begin review.")
        customer.status = Customer.Status.UNDER_REVIEW
        customer.save(update_fields=["status", "updated_at"])
        emit_event(
            tenant_id=customer.tenant_id,
            aggregate_type="Customer",
            aggregate_id=customer.id,
            event_type="CustomerReviewStarted",
            payload={
                "reason": reason,
                "actor_id": str(actor.id) if actor else None,
            },
        )
        return customer

    @staticmethod
    @transaction.atomic
    def approve_customer(*, customer, approver, reason=""):
        if customer.status != Customer.Status.UNDER_REVIEW:
            raise ValidationError("Customer must be UNDER_REVIEW to be approved.")
        customer.status = Customer.Status.APPROVED
        customer.approved_by = approver
        customer.approved_at = timezone.now()
        customer.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        emit_event(
            tenant_id=customer.tenant_id,
            aggregate_type="Customer",
            aggregate_id=customer.id,
            event_type="CustomerApproved",
            payload={"reason": reason, "approver_id": str(approver.id) if approver else None},
        )
        return customer

    @staticmethod
    @transaction.atomic
    def activate_customer(*, customer, actor=None, reason=""):
        if customer.status != Customer.Status.APPROVED:
            raise ValidationError("Customer must be APPROVED to be activated.")
        customer.status = Customer.Status.ACTIVE
        customer.save(update_fields=["status", "updated_at"])
        emit_event(
            tenant_id=customer.tenant_id,
            aggregate_type="Customer",
            aggregate_id=customer.id,
            event_type="CustomerActivated",
            payload={
                "reason": reason,
                "actor_id": str(actor.id) if actor else None,
            },
        )
        return customer

    @staticmethod
    @transaction.atomic
    def suspend_customer(*, customer, reason, actor=None):
        if customer.status != Customer.Status.ACTIVE:
            raise ValidationError("Customer must be ACTIVE to be suspended.")
        customer.status = Customer.Status.SUSPENDED
        customer.save(update_fields=["status", "updated_at"])
        emit_event(
            tenant_id=customer.tenant_id,
            aggregate_type="Customer",
            aggregate_id=customer.id,
            event_type="CustomerSuspended",
            payload={
                "reason": reason,
                "actor_id": str(actor.id) if actor else None,
            },
        )
        return customer

    @staticmethod
    @transaction.atomic
    def block_customer(*, customer, reason):
        customer.status = Customer.Status.BLOCKED
        customer.save(update_fields=["status", "updated_at"])
        emit_event(
            tenant_id=customer.tenant_id,
            aggregate_type="Customer",
            aggregate_id=customer.id,
            event_type="CustomerBlocked",
            payload={"reason": reason},
        )
        return customer

    @staticmethod
    @transaction.atomic
    def reactivate_customer(*, customer, reason, actor=None):
        if customer.status != Customer.Status.SUSPENDED:
            raise ValidationError("Customer must be SUSPENDED to be reactivated.")
        customer.status = Customer.Status.ACTIVE
        customer.save(update_fields=["status", "updated_at"])
        emit_event(
            tenant_id=customer.tenant_id,
            aggregate_type="Customer",
            aggregate_id=customer.id,
            event_type="CustomerReactivated",
            payload={
                "reason": reason,
                "actor_id": str(actor.id) if actor else None,
            },
        )
        return customer


class CustomerCreditPolicyService:
    """Service for evaluating customer credit policies."""

    @staticmethod
    def evaluate_order(*, customer, order_total):
        if customer.status != Customer.Status.ACTIVE:
            return {
                "eligible": False,
                "reason": f"Customer status is {customer.status}",
                "credit_status": customer.credit_status,
            }

        if customer.credit_status in [Customer.CreditStatus.BLOCKED, Customer.CreditStatus.CREDIT_HOLD]:
            return {
                "eligible": False,
                "reason": f"Customer credit status is {customer.credit_status}",
                "credit_status": customer.credit_status,
            }

        if hasattr(customer, "commercial_profile"):
            profile = customer.commercial_profile
            if profile.credit_limit > 0 and order_total > profile.credit_limit:
                # Typically, you'd check current balance + order_total, but the instructions say "doesn't exceed credit_limit (if set)"
                return {
                    "eligible": False,
                    "reason": "Order exceeds credit limit",
                    "credit_status": customer.credit_status,
                }

        return {"eligible": True, "reason": "", "credit_status": customer.credit_status}
