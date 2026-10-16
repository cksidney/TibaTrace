from celery import shared_task


@shared_task
def process_fiscal_outbox():
    from apps.prescription.fiscal import FiscalService
    from apps.prescription.fiscal_models import FiscalSubmission
    for row in FiscalSubmission.objects.filter(status__in=["NOT_CONFIGURED", "QUEUED"]).order_by("created_at")[:50]:
        FiscalService.submit(row)
    # Retry document creation independently; fiscal acceptance never depends
    # on a printer or the document queue being available.
    from django.db.models import CharField, Exists, OuterRef, Value
    from django.db.models.functions import Cast, Concat, Replace, Substr

    from apps.prescription.pos_printing_models import PosPrintDocument
    missing = FiscalSubmission.objects.filter(status="ACCEPTED").annotate(
        document_number=Concat(Value("VSCU-"), Substr(Replace(Cast("branch_id", CharField()), Value("-"), Value("")), 1, 8), Value("-"), Cast("invoice_number", CharField())),
    ).annotate(has_document=Exists(PosPrintDocument.all_objects.filter(tenant_id=OuterRef("tenant_id"), document_number=OuterRef("document_number")))).filter(has_document=False)
    for row in missing.order_by("updated_at")[:50]:
        FiscalService.queue_document(row)


@shared_task
def reconcile_checkout_providers():
    import logging

    from apps.prescription.checkout import CheckoutService
    from apps.prescription.payment_models import PaymentAttempt
    pending = PaymentAttempt.all_objects.filter(provider="MPESA", status__in=["STARTED", "ACCEPTED"]).select_related(
        "payment_tender__payment_intent__dispensing_episode", "payment_tender__payment_intent__retail_transaction", "payment_tender__created_by")
    for attempt in pending.order_by("created_at")[:50]:
        intent = attempt.payment_tender.payment_intent
        source = intent.retail_transaction if intent.retail_transaction_id else intent.dispensing_episode
        try:
            CheckoutService.query_provider(source=source, actor=attempt.payment_tender.created_by)
        except Exception:
            logging.getLogger(__name__).warning("Checkout provider reconciliation requires review", extra={"attempt_id": str(attempt.pk)})
