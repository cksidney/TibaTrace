"""Taxation & KRA eTIMS Fiscalization Pipeline."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Optional

from django.db import transaction
from django.utils import timezone

from apps.pricing.resolution import money
from apps.taxation.models import FiscalReceipt, TenantEtimsProfile
from apps.taxation.qr_generator import (
    build_kra_qr_verification_url,
    compute_offline_receipt_signature,
    construct_kra_qr_payload,
    generate_qr_svg,
)
from apps.taxation.vscu_client import VscuClient

logger = logging.getLogger(__name__)

VAT_RATE_A = Decimal("0.16")
DEFAULT_ITEM_CLASS_CODE = "51101500"  # UNSPSC code for Pharmaceutical products


class FiscalizationPipeline:
    """Manages the full fiscalization lifecycle for retail POS sales and refunds."""

    @classmethod
    def get_profile(cls, tenant) -> Optional[TenantEtimsProfile]:
        """Retrieve active TenantEtimsProfile if enabled."""
        profile = TenantEtimsProfile.all_objects.filter(
            tenant=tenant,
            is_enabled=True,
        ).first()
        return profile

    @classmethod
    @transaction.atomic
    def allocate_invoice_number(cls, profile: TenantEtimsProfile, receipt_type: str) -> int:
        """Atomically increment and allocate sequential invoice number."""
        locked = TenantEtimsProfile.all_objects.select_for_update().get(pk=profile.pk)
        if receipt_type == FiscalReceipt.ReceiptType.CREDIT_NOTE:
            locked.last_credit_note_number += 1
            num = locked.last_credit_note_number
            locked.save(update_fields=["last_credit_note_number", "updated_at"])
        else:
            locked.last_invoice_number += 1
            num = locked.last_invoice_number
            locked.save(update_fields=["last_invoice_number", "updated_at"])
        return num

    @classmethod
    def map_line_tax(cls, line) -> dict[str, Any]:
        """Classify line item according to Kenyan VAT & KRA eTIMS categories."""
        # CommercialSKU tax_category: "EXEMPT", "ZERO_RATED", "STANDARD"
        tax_category = getattr(line.sku, "tax_category", "STANDARD") or "STANDARD"
        total = money(line.line_total)
        quantity = Decimal(str(line.quantity))
        unit_price = money(line.unit_price)

        if tax_category.upper() == "EXEMPT":
            tax_ty_cd = "E"
            taxable_amt = total
            tax_amt = Decimal("0.00")
        elif tax_category.upper() == "ZERO_RATED":
            tax_ty_cd = "B"
            taxable_amt = total
            tax_amt = Decimal("0.00")
        else:
            # STANDARD 16% (VAT inclusive in retail pricing)
            tax_ty_cd = "A"
            # Net = Total / 1.16; VAT = Total - Net
            taxable_amt = money(total / (Decimal("1.00") + VAT_RATE_A))
            tax_amt = money(total - taxable_amt)

        item_cls_cd = getattr(line.sku, "item_classification_code", "") or DEFAULT_ITEM_CLASS_CODE

        return {
            "tax_ty_cd": tax_ty_cd,
            "taxable_amt": taxable_amt,
            "tax_amt": tax_amt,
            "total_amt": total,
            "item_cls_cd": item_cls_cd,
            "item_cd": line.sku.sku_code,
            "item_nm": line.description_snapshot,
            "unit": line.unit or "U",
            "quantity": quantity,
            "unit_price": unit_price,
        }

    @classmethod
    def build_vscu_sales_payload(
        cls,
        *,
        profile: TenantEtimsProfile,
        invoice_no: int,
        original_invoice_no: int,
        receipt_type: str,
        customer_pin: str,
        customer_name: str,
        customer_mobile: str,
        lines_tax_data: list[dict[str, Any]],
        totals: dict[str, Decimal],
        now_dt: Any,
        actor_name: str,
    ) -> dict[str, Any]:
        """Construct standard KRA eTIMS VSCU JSON payload."""
        date_str = now_dt.strftime("%Y%m%d")
        time_str = now_dt.strftime("%H%M%S")
        datetime_str = date_str + time_str

        is_refund = (receipt_type == FiscalReceipt.ReceiptType.CREDIT_NOTE)
        rcpt_ty_cd = "R" if is_refund else "S"

        item_list = []
        for idx, item in enumerate(lines_tax_data, start=1):
            qty = item["quantity"]
            if is_refund and qty > 0:
                qty = -qty
            item_list.append({
                "itemSeq": idx,
                "itemCd": item["item_cd"],
                "itemClsCd": item["item_cls_cd"],
                "itemNm": item["item_nm"],
                "bcd": None,
                "pkgUnitCd": "BX",
                "pkg": 1,
                "qtyUnitCd": "U",
                "qty": float(qty),
                "prc": float(item["unit_price"]),
                "splyAmt": float(item["taxable_amt"] if not is_refund else -item["taxable_amt"]),
                "dcRt": 0,
                "dcAmt": 0,
                "isrccCd": None,
                "isrccNm": None,
                "isrcRt": None,
                "isrcAmt": None,
                "taxTyCd": item["tax_ty_cd"],
                "taxblAmt": float(item["taxable_amt"] if not is_refund else -item["taxable_amt"]),
                "taxAmt": float(item["tax_amt"] if not is_refund else -item["tax_amt"]),
                "totAmt": float(item["total_amt"] if not is_refund else -item["total_amt"]),
            })

        sign = -1 if is_refund else 1

        payload = {
            "tin": profile.tin,
            "bhfId": profile.bhf_id,
            "invcNo": invoice_no,
            "orgInvcNo": original_invoice_no if is_refund else 0,
            "custTin": customer_pin or "",
            "custNm": customer_name or "",
            "salesTyCd": "N",
            "rcptTyCd": rcpt_ty_cd,
            "pmtTyCd": "01",
            "salesSttsCd": "02",
            "cfmDt": datetime_str,
            "salesDt": date_str,
            "stockRlsDt": datetime_str,
            "cnclReqDt": None,
            "cnclDt": None,
            "rfdDt": datetime_str if is_refund else None,
            "rfdRsnCd": "01" if is_refund else None,
            "totItemCnt": len(item_list),
            "taxblAmtA": float(totals["taxblAmtA"] * sign),
            "taxAmtA": float(totals["taxAmtA"] * sign),
            "taxblAmtB": float(totals["taxblAmtB"] * sign),
            "taxAmtB": float(totals["taxAmtB"] * sign),
            "taxblAmtC": float(totals["taxblAmtC"] * sign),
            "taxAmtC": float(totals["taxAmtC"] * sign),
            "taxblAmtD": float(totals["taxblAmtD"] * sign),
            "taxAmtD": float(totals["taxAmtD"] * sign),
            "taxblAmtE": float(totals["taxblAmtE"] * sign),
            "taxAmtE": float(totals["taxAmtE"] * sign),
            "totTaxblAmt": float(totals["totTaxblAmt"] * sign),
            "totTaxAmt": float(totals["totTaxAmt"] * sign),
            "totAmt": float(totals["totAmt"] * sign),
            "prchrAcptYn": "N",
            "remark": "TibaTrace POS Transaction",
            "regrId": actor_name,
            "regrNm": actor_name,
            "modrId": actor_name,
            "modrNm": actor_name,
            "receipt": {
                "custTin": customer_pin or "",
                "custMblNo": customer_mobile or "",
                "rcptPbctDt": datetime_str,
                "trdeNm": profile.branch_name or "TibaTrace",
                "adrs": "",
                "topMsg": profile.taxpayer_name or "TibaTrace Healthcare",
                "btmMsg": "Thank you for your business",
                "prchrAcptYn": "N",
            },
            "itemList": item_list,
        }
        return payload

    @classmethod
    def process_retail_sale(
        cls,
        *,
        transaction_record,
        receipt,
        actor,
    ) -> Optional[FiscalReceipt]:
        """Fiscalize a completed retail POS sale."""
        profile = cls.get_profile(transaction_record.tenant)
        if profile is None or not profile.is_enabled:
            return None

        # Determine customer metadata if present
        customer_pin = ""
        customer_name = ""
        customer_mobile = ""
        if transaction_record.customer:
            customer_pin = getattr(transaction_record.customer, "tax_pin", "") or ""
            customer_name = getattr(transaction_record.customer, "name", "") or ""
            customer_mobile = getattr(transaction_record.customer, "phone_number", "") or ""

        # Map lines and compute tax buckets
        lines = list(transaction_record.lines.select_related("sku").order_by("pk"))
        lines_tax_data = [cls.map_line_tax(line) for line in lines]

        totals = {
            "taxblAmtA": Decimal("0.00"),
            "taxAmtA": Decimal("0.00"),
            "taxblAmtB": Decimal("0.00"),
            "taxAmtB": Decimal("0.00"),
            "taxblAmtC": Decimal("0.00"),
            "taxAmtC": Decimal("0.00"),
            "taxblAmtD": Decimal("0.00"),
            "taxAmtD": Decimal("0.00"),
            "taxblAmtE": Decimal("0.00"),
            "taxAmtE": Decimal("0.00"),
            "totTaxblAmt": Decimal("0.00"),
            "totTaxAmt": Decimal("0.00"),
            "totAmt": Decimal("0.00"),
        }

        for item in lines_tax_data:
            tax_code = item["tax_ty_cd"]
            totals[f"taxblAmt{tax_code}"] += item["taxable_amt"]
            totals[f"taxAmt{tax_code}"] += item["tax_amt"]
            totals["totTaxblAmt"] += item["taxable_amt"]
            totals["totTaxAmt"] += item["tax_amt"]
            totals["totAmt"] += item["total_amt"]

        invoice_no = cls.allocate_invoice_number(profile, FiscalReceipt.ReceiptType.SALE)
        now_dt = timezone.localtime(receipt.settled_at or timezone.now())
        actor_name = getattr(actor, "username", "pos-cashier")

        raw_payload = cls.build_vscu_sales_payload(
            profile=profile,
            invoice_no=invoice_no,
            original_invoice_no=0,
            receipt_type=FiscalReceipt.ReceiptType.SALE,
            customer_pin=customer_pin,
            customer_name=customer_name,
            customer_mobile=customer_mobile,
            lines_tax_data=lines_tax_data,
            totals=totals,
            now_dt=now_dt,
            actor_name=actor_name,
        )

        date_str = now_dt.strftime("%Y%m%d%H%M%S")
        offline_internal, offline_sign = compute_offline_receipt_signature(
            tin=profile.tin,
            bhf_id=profile.bhf_id,
            invoice_no=invoice_no,
            total_amount=str(totals["totAmt"]),
            date_str=date_str,
            secret_key=profile.cm_key,
        )

        qr_payload = construct_kra_qr_payload(
            tin=profile.tin,
            bhf_id=profile.bhf_id,
            sdc_id=profile.sdc_id or profile.dvc_srl_no,
            invoice_no=invoice_no,
            receipt_date_str=date_str,
            internal_data=offline_internal,
            receipt_signature=offline_sign,
        )
        qr_url = build_kra_qr_verification_url(payload=qr_payload, environment=profile.environment)
        qr_svg = generate_qr_svg(qr_url)

        fiscal_receipt = FiscalReceipt.all_objects.create(
            tenant=transaction_record.tenant,
            pos_transaction=transaction_record,
            retail_cash_receipt=receipt,
            receipt_type=FiscalReceipt.ReceiptType.SALE,
            invoice_number=invoice_no,
            original_invoice_number=0,
            sales_type_code="N",
            receipt_type_code="S",
            payment_type_code="01",
            customer_pin=customer_pin,
            customer_name=customer_name,
            customer_mobile=customer_mobile,
            taxable_amount_a=totals["taxblAmtA"],
            tax_amount_a=totals["taxAmtA"],
            taxable_amount_b=totals["taxblAmtB"],
            tax_amount_b=totals["taxAmtB"],
            taxable_amount_c=totals["taxblAmtC"],
            tax_amount_c=totals["taxAmtC"],
            taxable_amount_d=totals["taxblAmtD"],
            tax_amount_d=totals["taxAmtD"],
            taxable_amount_e=totals["taxblAmtE"],
            tax_amount_e=totals["taxAmtE"],
            total_taxable_amount=totals["totTaxblAmt"],
            total_tax_amount=totals["totTaxAmt"],
            total_amount=totals["totAmt"],
            currency=transaction_record.currency,
            internal_data=offline_internal,
            receipt_signature=offline_sign,
            qr_code_url=qr_url,
            qr_code_image_data=qr_svg,
            submission_status=FiscalReceipt.SubmissionStatus.PENDING,
            attempt_count=0,
            raw_request_payload=raw_payload,
            items_snapshot=raw_payload["itemList"],
        )

        # Attempt immediate transmission if enabled and configured
        if profile.auto_fiscalize_pos_sales and profile.is_configured:
            cls.transmit_to_vscu(fiscal_receipt=fiscal_receipt, profile=profile)

        return fiscal_receipt

    @classmethod
    def process_retail_refund(
        cls,
        *,
        receipt,
        actor,
    ) -> Optional[FiscalReceipt]:
        """Fiscalize a completed retail cash refund / credit note."""
        tenant = receipt.tenant
        profile = cls.get_profile(tenant)
        if profile is None or not profile.is_enabled:
            return None

        original_fiscal = FiscalReceipt.all_objects.filter(
            tenant=tenant,
            pos_transaction=receipt.original_receipt.transaction,
            receipt_type=FiscalReceipt.ReceiptType.SALE,
        ).first()

        original_invoice_no = original_fiscal.invoice_number if original_fiscal else 0

        # Refund items
        refund_lines = list(receipt.refund_request.lines.select_related("original_line__sku"))
        lines_tax_data = []
        for r_line in refund_lines:
            orig = r_line.original_line
            tax_category = getattr(orig.sku, "tax_category", "STANDARD") or "STANDARD"
            amt = money(r_line.amount)
            qty = Decimal(str(r_line.quantity))
            unit_price = money(amt / qty) if qty > 0 else money(0)

            if tax_category.upper() == "EXEMPT":
                tax_ty_cd = "E"
                taxable_amt = amt
                tax_amt = Decimal("0.00")
            elif tax_category.upper() == "ZERO_RATED":
                tax_ty_cd = "B"
                taxable_amt = amt
                tax_amt = Decimal("0.00")
            else:
                tax_ty_cd = "A"
                taxable_amt = money(amt / (Decimal("1.00") + VAT_RATE_A))
                tax_amt = money(amt - taxable_amt)

            lines_tax_data.append({
                "tax_ty_cd": tax_ty_cd,
                "taxable_amt": taxable_amt,
                "tax_amt": tax_amt,
                "total_amt": amt,
                "item_cls_cd": DEFAULT_ITEM_CLASS_CODE,
                "item_cd": orig.sku.sku_code,
                "item_nm": orig.description_snapshot,
                "unit": orig.unit or "U",
                "quantity": qty,
                "unit_price": unit_price,
            })

        totals = {
            "taxblAmtA": Decimal("0.00"),
            "taxAmtA": Decimal("0.00"),
            "taxblAmtB": Decimal("0.00"),
            "taxAmtB": Decimal("0.00"),
            "taxblAmtC": Decimal("0.00"),
            "taxAmtC": Decimal("0.00"),
            "taxblAmtD": Decimal("0.00"),
            "taxAmtD": Decimal("0.00"),
            "taxblAmtE": Decimal("0.00"),
            "taxAmtE": Decimal("0.00"),
            "totTaxblAmt": Decimal("0.00"),
            "totTaxAmt": Decimal("0.00"),
            "totAmt": Decimal("0.00"),
        }

        for item in lines_tax_data:
            tax_code = item["tax_ty_cd"]
            totals[f"taxblAmt{tax_code}"] += item["taxable_amt"]
            totals[f"taxAmt{tax_code}"] += item["tax_amt"]
            totals["totTaxblAmt"] += item["taxable_amt"]
            totals["totTaxAmt"] += item["tax_amt"]
            totals["totAmt"] += item["total_amt"]

        invoice_no = cls.allocate_invoice_number(profile, FiscalReceipt.ReceiptType.CREDIT_NOTE)
        now_dt = timezone.localtime(receipt.created_at or timezone.now())
        actor_name = getattr(actor, "username", "pos-cashier")

        raw_payload = cls.build_vscu_sales_payload(
            profile=profile,
            invoice_no=invoice_no,
            original_invoice_no=original_invoice_no,
            receipt_type=FiscalReceipt.ReceiptType.CREDIT_NOTE,
            customer_pin="",
            customer_name="",
            customer_mobile="",
            lines_tax_data=lines_tax_data,
            totals=totals,
            now_dt=now_dt,
            actor_name=actor_name,
        )

        date_str = now_dt.strftime("%Y%m%d%H%M%S")
        offline_internal, offline_sign = compute_offline_receipt_signature(
            tin=profile.tin,
            bhf_id=profile.bhf_id,
            invoice_no=invoice_no,
            total_amount=str(totals["totAmt"]),
            date_str=date_str,
            secret_key=profile.cm_key,
        )

        qr_payload = construct_kra_qr_payload(
            tin=profile.tin,
            bhf_id=profile.bhf_id,
            sdc_id=profile.sdc_id or profile.dvc_srl_no,
            invoice_no=invoice_no,
            receipt_date_str=date_str,
            internal_data=offline_internal,
            receipt_signature=offline_sign,
        )
        qr_url = build_kra_qr_verification_url(payload=qr_payload, environment=profile.environment)
        qr_svg = generate_qr_svg(qr_url)

        fiscal_receipt = FiscalReceipt.all_objects.create(
            tenant=tenant,
            pos_transaction=receipt.original_receipt.transaction,
            retail_cash_refund=receipt,
            receipt_type=FiscalReceipt.ReceiptType.CREDIT_NOTE,
            invoice_number=invoice_no,
            original_invoice_number=original_invoice_no,
            sales_type_code="N",
            receipt_type_code="R",
            payment_type_code="01",
            taxable_amount_a=totals["taxblAmtA"],
            tax_amount_a=totals["taxAmtA"],
            taxable_amount_b=totals["taxblAmtB"],
            tax_amount_b=totals["taxAmtB"],
            taxable_amount_c=totals["taxblAmtC"],
            tax_amount_c=totals["taxAmtC"],
            taxable_amount_d=totals["taxblAmtD"],
            tax_amount_d=totals["taxAmtD"],
            taxable_amount_e=totals["taxblAmtE"],
            tax_amount_e=totals["taxAmtE"],
            total_taxable_amount=totals["totTaxblAmt"],
            total_tax_amount=totals["totTaxAmt"],
            total_amount=totals["totAmt"],
            currency=receipt.currency,
            internal_data=offline_internal,
            receipt_signature=offline_sign,
            qr_code_url=qr_url,
            qr_code_image_data=qr_svg,
            submission_status=FiscalReceipt.SubmissionStatus.PENDING,
            attempt_count=0,
            raw_request_payload=raw_payload,
            items_snapshot=raw_payload["itemList"],
        )

        if profile.auto_fiscalize_pos_sales and profile.is_configured:
            cls.transmit_to_vscu(fiscal_receipt=fiscal_receipt, profile=profile)

        return fiscal_receipt

    @classmethod
    def transmit_to_vscu(
        cls,
        fiscal_receipt: FiscalReceipt,
        profile: TenantEtimsProfile,
    ) -> bool:
        """Transmit fiscal receipt to KRA VSCU and handle response."""
        client = VscuClient(profile)
        res = client.transmit_sales(fiscal_receipt)

        fiscal_receipt.attempt_count += 1
        if res["success"]:
            data = res.get("data", {})
            sdc_id = data.get("sdcId") or profile.sdc_id or profile.dvc_srl_no
            intrl_data = data.get("intrlData") or fiscal_receipt.internal_data
            rcpt_sign = data.get("rcptSign") or fiscal_receipt.receipt_signature
            rcpt_date = data.get("vsdcRcptPbctDate") or timezone.now().strftime("%Y%m%d%H%M%S")

            # Re-generate QR code with authoritative KRA VSCU data
            qr_payload = construct_kra_qr_payload(
                tin=profile.tin,
                bhf_id=profile.bhf_id,
                sdc_id=sdc_id,
                invoice_no=fiscal_receipt.invoice_number,
                receipt_date_str=rcpt_date,
                internal_data=intrl_data,
                receipt_signature=rcpt_sign,
            )
            qr_url = build_kra_qr_verification_url(payload=qr_payload, environment=profile.environment)
            qr_svg = generate_qr_svg(qr_url)

            fiscal_receipt.submission_status = FiscalReceipt.SubmissionStatus.SUBMITTED
            fiscal_receipt.internal_data = intrl_data
            fiscal_receipt.receipt_signature = rcpt_sign
            fiscal_receipt.qr_code_url = qr_url
            fiscal_receipt.qr_code_image_data = qr_svg
            fiscal_receipt.submitted_at = timezone.now()
            fiscal_receipt.raw_response_payload = res.get("raw_response", {})
            fiscal_receipt.last_error = ""
            fiscal_receipt.save(
                update_fields=[
                    "submission_status",
                    "internal_data",
                    "receipt_signature",
                    "qr_code_url",
                    "qr_code_image_data",
                    "submitted_at",
                    "raw_response_payload",
                    "last_error",
                    "attempt_count",
                    "updated_at",
                ]
            )
            return True
        else:
            fiscal_receipt.submission_status = FiscalReceipt.SubmissionStatus.FAILED
            fiscal_receipt.last_error = res.get("error", "Unknown transmission error")
            fiscal_receipt.next_retry_at = timezone.now() + timezone.timedelta(minutes=5)
            fiscal_receipt.save(
                update_fields=[
                    "submission_status",
                    "last_error",
                    "next_retry_at",
                    "attempt_count",
                    "updated_at",
                ]
            )
            return False
