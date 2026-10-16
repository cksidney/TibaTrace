"""KRA VSCU outbox. A timeout never becomes a second fiscal invoice."""

import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from urllib.request import Request, urlopen

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.prescription.fiscal_models import FiscalSubmission
from apps.prescription.payment_connections import vscu_config


class FiscalService:
    @staticmethod
    def kind(source):
        if source._meta.model_name == "retailcashrefund":
            return "RETAIL_REFUND"
        return "RETAIL" if source._meta.model_name == "postransaction" else "PRESCRIPTION"

    @classmethod
    def enqueue(cls, *, source):
        if cls.kind(source) == "RETAIL" and source.state != "COMPLETED":
            return None
        if cls.kind(source) == "PRESCRIPTION" and source.payment_state != "PAID":
            return None
        branch = source.register.location if cls.kind(source) == "RETAIL_REFUND" else source.branch
        row, _ = FiscalSubmission.objects.get_or_create(
            tenant=source.tenant, branch=branch, source_kind=cls.kind(source), source_id=source.pk
        )
        return row

    @classmethod
    def refund_payload(cls, row, config):
        from apps.pos_transactions.models import RetailCashRefund, RetailRefundLine
        refund = RetailCashRefund.all_objects.select_related("original_receipt__transaction").get(pk=row.source_id, tenant=row.tenant)
        sale = refund.original_receipt.transaction
        # Credit notes use the original fiscal device's branch and invoice.
        if sale.branch_id != row.branch_id:
            raise ValidationError("Fiscal credit notes must be issued by the original sale branch's VSCU.")
        original = FiscalSubmission.objects.filter(tenant=row.tenant, source_kind="RETAIL", source_id=sale.pk, status="ACCEPTED").first()
        if not original:
            raise ValidationError("The original fiscal invoice must be accepted before issuing its credit note.")
        payload = deepcopy(original.payload)
        payload.update(trdInvcNo=refund.refund_number, orgInvcNo=original.invoice_number, rcptTyCd="R", salesSttsCd="05", rfdRsnCd="06", rfdDt=timezone.localtime().strftime("%Y%m%d%H%M%S"), remark=refund.refund_request.reason[:400])
        items = []
        for line in RetailRefundLine.all_objects.filter(tenant=row.tenant, refund_request=refund.refund_request).select_related("original_line__sku"):
            original_line = line.original_line
            code = config.get("items", {}).get(str(original_line.sku_id), {}).get("item_code")
            matches = [item for item in payload["itemList"] if item["itemCd"] == code]
            if len(matches) != 1:
                raise ValidationError("Credit note item mapping must match one original fiscal invoice line.")
            item = deepcopy(matches[0])
            ratio = line.quantity / original_line.quantity
            tax = (original_line.tax_amount * ratio).quantize(Decimal("0.01"))
            discount = (original_line.discount_amount * ratio).quantize(Decimal("0.01"))
            item.update(itemSeq=len(items) + 1, qty=str(line.quantity), splyAmt=str(original_line.unit_price * line.quantity), dcAmt=str(discount), taxblAmt=str(line.amount - tax), taxAmt=str(tax), totAmt=str(line.amount))
            items.append(item)
        for code in "ABCDE":
            payload[f"taxblAmt{code}"] = str(sum((Decimal(item["taxblAmt"]) for item in items if item["taxTyCd"] == code), Decimal(0)))
            payload[f"taxAmt{code}"] = str(sum((Decimal(item["taxAmt"]) for item in items if item["taxTyCd"] == code), Decimal(0)))
        payload.update(itemList=items, totItemCnt=len(items), totAmt=str(refund.amount), totTaxAmt=str(sum((Decimal(item["taxAmt"]) for item in items), Decimal(0))), totTaxblAmt=str(sum((Decimal(item["taxblAmt"]) for item in items), Decimal(0))))
        return payload

    @classmethod
    def status(cls, source):
        row = FiscalSubmission.objects.filter(
            tenant=source.tenant, source_kind=cls.kind(source), source_id=source.pk
        ).first()
        if not row:
            return {"status": "NOT_DUE", "receipt": None, "message": "Fiscal receipt is issued after full settlement."}
        return {
            "id": str(row.pk),
            "status": row.status,
            "receipt": row.response if row.status == "ACCEPTED" else None,
            "message": row.error or ("VSCU configuration required" if row.status == "NOT_CONFIGURED" else ""),
        }

    @classmethod
    @transaction.atomic
    def prepare(cls, row):
        from apps.organizations.models import Location
        from apps.pos_transactions.models import PosTransaction, PosTransactionLine
        from apps.prescription.models import DispensingEpisode

        row = FiscalSubmission.objects.select_for_update().get(pk=row.pk)
        if row.payload:
            return row
        config = vscu_config(tenant=row.tenant, branch=row.branch)
        Location.all_objects.select_for_update().get(pk=row.branch_id)
        if row.source_kind == "RETAIL_REFUND":
            payload = cls.refund_payload(row, config)
            return cls.freeze(row, payload, config)
        if row.source_kind == "RETAIL":
            source = PosTransaction.all_objects.get(pk=row.source_id, tenant=row.tenant)
            lines = PosTransactionLine.all_objects.filter(tenant=row.tenant, transaction=source).select_related("sku")
            rows = [
                (line.sku, line.quantity, line.unit_price, line.discount_amount, line.tax_amount, line.line_total)
                for line in lines
            ]
            number = source.transaction_number
        else:
            source = DispensingEpisode.all_objects.select_related("sales_order").get(
                pk=row.source_id, tenant=row.tenant
            )
            if not source.sales_order:
                raise ValidationError("Fiscal invoice requires the priced sales order.")
            from apps.sales.models import SalesOrderLine
            rows = [
                (
                    line.sku,
                    line.approved_quantity or line.requested_quantity,
                    line.agreed_unit_price,
                    line.discount_amount,
                    line.tax_amount,
                    line.line_total,
                )
                for line in SalesOrderLine.all_objects.filter(tenant=row.tenant, sales_order=source.sales_order).select_related("sku")
            ]
            number = source.dispensing_number
        items = []
        now = timezone.localtime()
        payload = {
            "tin": config["tin"],
            "bhfId": config["bhf_id"],
            "trdInvcNo": number,
            "orgInvcNo": 0,
            "salesTyCd": "N",
            "rcptTyCd": "S",
            "pmtTyCd": None,
            "salesSttsCd": "02",
            "cfmDt": now.strftime("%Y%m%d%H%M%S"),
            "salesDt": now.strftime("%Y%m%d"),
            "prchrAcptcYn": "N",
            "regrId": "TibaTrace",
            "regrNm": "TibaTrace",
            "modrId": "TibaTrace",
            "modrNm": "TibaTrace",
        }
        for code in "ABCDE":
            payload[f"taxblAmt{code}"] = "0.00"
            payload[f"taxAmt{code}"] = "0.00"
            payload[f"taxRt{code}"] = str(config.get("tax_rates", {}).get(code, 0))
        for index, (sku, qty, price, discount, tax, total) in enumerate(rows, 1):
            mapping = config.get("items", {}).get(str(sku.pk), {})
            required = {"item_code", "classification_code", "package_unit", "quantity_unit", "tax_type"}
            if not required <= mapping.keys() or mapping.get("tax_type") not in {"A", "B", "C", "D", "E"}:
                raise ValidationError("VSCU item, unit and tax mappings are incomplete.")
            code = mapping["tax_type"]
            taxable = total - tax
            expected_tax = (taxable * Decimal(payload[f"taxRt{code}"]) / 100).quantize(Decimal("0.01"))
            if expected_tax != tax:
                raise ValidationError(
                    "Fiscal tax mapping does not match the recorded sale tax; review pricing before submission."
                )
            payload[f"taxblAmt{code}"] = str(Decimal(payload[f"taxblAmt{code}"]) + taxable)
            payload[f"taxAmt{code}"] = str(Decimal(payload[f"taxAmt{code}"]) + tax)
            items.append(
                {
                    "itemSeq": index,
                    "itemCd": mapping["item_code"],
                    "itemClsCd": mapping["classification_code"],
                    "itemNm": sku.display_name,
                    "pkgUnitCd": mapping["package_unit"],
                    "pkg": 1,
                    "qtyUnitCd": mapping["quantity_unit"],
                    "qty": str(qty),
                    "prc": str(price),
                    "splyAmt": str(price * qty),
                    "dcRt": 0,
                    "dcAmt": str(discount),
                    "taxTyCd": code,
                    "taxblAmt": str(taxable),
                    "taxAmt": str(tax),
                    "totAmt": str(total),
                }
            )
        if not items:
            raise ValidationError("Fiscal invoice has no itemized sale lines.")
        payload.update(
            totItemCnt=len(items),
            itemList=items,
            totTaxblAmt=str(sum((Decimal(x["taxblAmt"]) for x in items), Decimal(0))),
            totTaxAmt=str(sum((Decimal(x["taxAmt"]) for x in items), Decimal(0))),
            totAmt=str(sum((Decimal(x["totAmt"]) for x in items), Decimal(0))),
        )
        due = source.total if row.source_kind == "RETAIL" else source.sales_order.total
        if Decimal(payload["totAmt"]) != due:
            raise ValidationError("Fiscal item totals do not match the paid sale.")
        return cls.freeze(row, payload, config)

    @staticmethod
    def freeze(row, payload, config):
        last = FiscalSubmission.objects.filter(tenant=row.tenant, branch=row.branch).aggregate(n=Max("invoice_number"))[
            "n"
        ]
        row.invoice_number = max(last or 0, int(config.get("last_invoice_number", 0))) + 1
        payload["invcNo"] = row.invoice_number
        payload["receipt"] = {"rptNo": row.invoice_number, "prchrAcptcYn": "N"}
        row.payload = payload
        row.payload_sha256 = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        row.status = "QUEUED"
        row.error = ""
        row.save()
        return row

    @classmethod
    def submit(cls, row, transport=None):
        try:
            row = cls.prepare(row)
        except ValidationError as exc:
            FiscalSubmission.objects.filter(pk=row.pk, payload={}).update(error=" ".join(exc.messages)[:300])
            return
        with transaction.atomic():
            row = FiscalSubmission.objects.select_for_update().get(pk=row.pk)
            if row.status != "QUEUED":
                return  # SENDING after a process crash also requires reconciliation.
            row.status = "SENDING"
            row.attempts += 1
            row.save(update_fields=["status", "attempts", "updated_at"])
        try:
            config = vscu_config(tenant=row.tenant, branch=row.branch)
            if transport:
                result = transport(row.payload)
            else:
                request = Request(
                    config["base_url"].rstrip("/") + "/trnsSales/saveSales",
                    data=json.dumps(row.payload).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=25) as response:
                    result = json.loads(response.read(262144))
            data = result.get("data") or {}
            accepted = result.get("resultCd") == "000" and all(
                data.get(k) for k in ("rcptNo", "rcptSign", "intrlData", "sdcId")
            )
            row.status = "ACCEPTED" if accepted else "REJECTED"
            row.response = (
                {
                    k: data[k]
                    for k in ("rcptNo", "rcptSign", "intrlData", "sdcId", "mrcNo", "VSCURcptPbctDate")
                    if k in data
                }
                if accepted
                else {}
            )
            row.error = "" if accepted else "VSCU refused the invoice or returned incomplete receipt evidence."
        except Exception:
            row.status = "UNKNOWN"
            row.error = "VSCU outcome is unknown. Reconcile this invoice number before resubmission."
        row.save(update_fields=["status", "response", "error", "updated_at"])
        if row.status == "ACCEPTED":
            try:
                cls.queue_document(row)
            except Exception:
                import logging
                logging.getLogger(__name__).warning("Accepted fiscal document needs queue recovery", extra={"submission_id": str(row.pk)})

    @staticmethod
    @transaction.atomic
    def queue_document(row):
        from apps.pos_transactions.models import PosTransaction, RetailCashRefund
        from apps.prescription.models import DispensingEpisode
        from apps.prescription.payment_models import PaymentIntent
        from apps.prescription.pos_printing_models import PosPrintDocument, PosPrintJob
        from apps.prescription.pos_printing_services import _hash_snapshot
        row = FiscalSubmission.objects.select_for_update().get(pk=row.pk)
        if row.status != "ACCEPTED":
            return
        number = f"VSCU-{row.branch_id.hex[:8]}-{row.invoice_number}"
        existing = PosPrintDocument.all_objects.filter(tenant=row.tenant, document_number=number).first()
        if existing:
            return
        if row.source_kind == "RETAIL_REFUND":
            source = RetailCashRefund.all_objects.get(tenant=row.tenant, pk=row.source_id)
            device_id, session, actor = source.device_id, source.register_session, source.created_by
        else:
            source = (PosTransaction if row.source_kind == "RETAIL" else DispensingEpisode).all_objects.get(tenant=row.tenant, pk=row.source_id)
            relation = {"retail_transaction": source} if row.source_kind == "RETAIL" else {"dispensing_episode": source}
            intent = PaymentIntent.all_objects.filter(tenant=row.tenant, **relation).first()
            device_id = intent.device_id if intent else getattr(source, "device_id", "")
            session = source.register_session if row.source_kind == "RETAIL" else source.payment_register_session
            actor = intent.created_by if intent else None
        kind = "FISCAL_CREDIT_NOTE" if row.source_kind == "RETAIL_REFUND" else "FISCAL_RECEIPT"
        snapshot = {"document_type": kind, "document_number": number, "issued_at": row.updated_at.isoformat(),
                    "lines": [{"description": item["itemNm"], "quantity": item["qty"], "line_total": item["totAmt"]} for item in row.payload["itemList"]],
                    "totals": {"total": row.payload["totAmt"], "tax_total": row.payload["totTaxAmt"]},
                    "payment": {"currency": "KES"}, "fiscal": {"invoice_number": row.invoice_number, "original_invoice_number": row.payload["orgInvcNo"], "taxpayer_pin": row.payload["tin"], **row.response},
                    "disclaimer": "VSCU credit note" if kind == "FISCAL_CREDIT_NOTE" else "VSCU fiscal receipt"}
        document = PosPrintDocument.all_objects.create(tenant=row.tenant, document_type=kind, document_number=number,
            snapshot=snapshot, document_hash=_hash_snapshot(snapshot), register_session=session, created_by=actor)
        PosPrintJob.all_objects.create(tenant=row.tenant, document=document, branch=row.branch, device_id=device_id,
            transport="SIMULATOR", copy_classification="ORIGINAL", copy_number=1, requested_by=actor, idempotency_key=f"fiscal-original:{row.pk}")
