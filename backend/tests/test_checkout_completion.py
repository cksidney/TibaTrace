from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from tests.test_pos_enterprise_dispensing import domain, setup_domain  # noqa: F401
from tests.test_pos_retail_transactions import prepare_sale_for_payment, world  # noqa: F401

from apps.inventory.models import InventoryReservation
from apps.pos_shift.cash_control import CashControlService
from apps.pos_transactions.models import PosTransaction, RetailCashReceipt
from apps.prescription.fiscal import FiscalService
from apps.prescription.fiscal_models import FiscalSubmission
from apps.prescription.payment_models import PaymentAttempt, PaymentSettlement, PaymentTender
from apps.taxation.models import FiscalReceipt, TenantEtimsProfile

pytestmark = pytest.mark.django_db


def collect(world, sale_id, *, amount="100.00", received="100.00", method="CASH", key="part-1", reference=""):  # noqa: F811
    return world["client"].post(
        f"/api/pos/retail/transactions/{sale_id}/checkout/",
        {
            "operation": "collect",
            "device_id": "POS-RETAIL-01",
            "amount": amount,
            "cash_received": received,
            "tender_type": method,
            "idempotency_key": key,
            "reference": reference,
        },
        format="json",
    )


def test_split_cash_card_reserves_then_completes_once_and_cash_report_excludes_card(world):  # noqa: F811
    draft = prepare_sale_for_payment(world)
    response = collect(world, draft["id"], received="120")
    assert response.status_code == 200, response.data
    assert response.data["intent"]["amount_remaining"] == "150.00"
    sale = PosTransaction.all_objects.get(pk=draft["id"])
    assert sale.state == "PAYMENT_IN_PROGRESS"
    assert InventoryReservation.all_objects.filter(source_document=draft["id"], status="ALLOCATED").exists(), list(InventoryReservation.all_objects.values("id", "source_document", "purpose", "status"))
    assert not RetailCashReceipt.all_objects.filter(transaction=sale).exists()
    response = collect(
        world, draft["id"], amount="150", received="0", method="CARD", key="part-2", reference="TERM-001"
    )
    assert response.status_code == 200, response.data
    assert response.data["intent"]["status"] == "SETTLED"
    sale.refresh_from_db()
    receipt = RetailCashReceipt.all_objects.get(transaction=sale)
    assert sale.state == "COMPLETED" and receipt.tender_type == "SPLIT"
    assert receipt.cash_received == Decimal("120") and receipt.change_due == Decimal("20")
    breakdown = CashControlService.tender_breakdown(session=sale.register_session)
    assert breakdown.cash == Decimal("100") and breakdown.non_cash == Decimal("150")
    assert (
        collect(
            world, draft["id"], amount="150", received="0", method="CARD", key="part-2", reference="TERM-001"
        ).status_code
        == 200
    )
    assert PaymentSettlement.all_objects.filter(payment_tender__payment_intent__retail_transaction=sale).count() == 2
    assert world["client"].post(f"/api/pos/retail/transactions/{sale.pk}/checkout/", {"operation": "finish", "device_id": "POS-RETAIL-01"}, format="json").status_code == 200


def test_payment_retry_key_cannot_change_amount_cash_or_reference(world):  # noqa: F811
    draft = prepare_sale_for_payment(world)
    assert collect(world, draft["id"]).status_code == 200
    for overrides in ({"amount": "110"}, {"received": "150"}, {"method": "CARD", "reference": "A"}):
        response = collect(world, draft["id"], **overrides)
        assert response.status_code == 400, response.data
    assert PaymentSettlement.all_objects.count() == 1


def test_short_cash_or_missing_card_reference_creates_no_payment_or_reservation(world):  # noqa: F811
    draft = prepare_sale_for_payment(world)
    assert collect(world, draft["id"], received="99").status_code == 400
    assert collect(world, draft["id"], method="CARD", reference="").status_code == 400
    assert not PaymentTender.all_objects.exists()
    assert not InventoryReservation.all_objects.filter(source_document=draft["id"]).exists()


def test_closed_shift_and_foreign_device_cannot_collect(world):  # noqa: F811
    draft = prepare_sale_for_payment(world)
    sale = PosTransaction.all_objects.get(pk=draft["id"])
    sale.operator_shift.state = "CLOSED"
    sale.operator_shift.save(update_fields=["state"])
    assert collect(world, draft["id"]).status_code == 400
    assert not PaymentSettlement.all_objects.exists()


def test_mpesa_without_supplied_configuration_never_initiates_or_creates_a_settlement(world):  # noqa: F811
    draft = prepare_sale_for_payment(world)
    response = world["client"].post(
        f"/api/pos/retail/transactions/{draft['id']}/checkout/",
        {
            "operation": "initiate",
            "device_id": "POS-RETAIL-01",
            "amount": "250",
            "idempotency_key": "mpesa-1",
            "phone_number": "0712345678",
        },
        format="json",
    )
    assert response.status_code == 400
    assert not PaymentSettlement.all_objects.exists()


@pytest.mark.parametrize("completion_path", ["QUERY", "CALLBACK", "EARLY_CALLBACK"])
def test_tenant_card_adapter_initiates_and_reconciles_without_manual_card_data(world, monkeypatch, completion_path):  # noqa: F811
    import json

    from apps.prescription.payment_providers import ADAPTERS, InitiationResult, ProviderEvent

    observed = {}

    def callback(attempt, signature):
        return world["client"].post(
            "/api/pos/payments/providers/TEST_ACQUIRER/callback/",
            {
                "request_reference": attempt.request_reference,
                "provider_reference": "ACQ-REFERENCE-01",
                "status": "SUCCEEDED",
                "amount": str(attempt.requested_amount),
                "currency": "KES",
                "event_id": "ACQ-CALLBACK-01",
            },
            format="json",
            HTTP_X_TEST_SIGNATURE=signature,
        )

    class CardAdapter:
        provider_code = "TEST_ACQUIRER"

        def __init__(self, *, tenant, branch, config, credentials):  # noqa: ARG002
            self.config = config
            self.credentials = credentials

        def validate_configuration(self, *, tenant, branch=None):  # noqa: ARG002
            assert self.credentials["api_key"] == "tenant-card-secret"

        def initiate(self, *, attempt, context):
            observed["context"] = context
            observed["calls"] = observed.get("calls", 0) + 1
            if completion_path == "EARLY_CALLBACK":
                assert callback(attempt, "valid").status_code == 202
            return InitiationResult(
                accepted=True,
                provider_reference="ACQ-REFERENCE-01",
                request_reference=attempt.request_reference,
                provider_status="ACCEPTED",
            )

        def query_status(self, *, attempt):
            return ProviderEvent(
                provider_reference=attempt.provider_reference,
                request_reference=attempt.request_reference,
                event_type="PAYMENT",
                status="SUCCEEDED",
                amount=attempt.requested_amount,
                currency="KES",
                event_id="ACQ-EVENT-01",
            )

        def authenticate_event(self, *, headers, payload, raw_body=b""):  # noqa: ARG002
            return headers.get("X-Test-Signature") == "valid" and b'"request_reference"' in raw_body

        def parse_event(self, *, headers, payload):  # noqa: ARG002
            return ProviderEvent(
                provider_reference=payload["provider_reference"],
                request_reference=payload["request_reference"],
                event_type="PAYMENT",
                status=payload["status"],
                amount=Decimal(payload["amount"]),
                currency=payload["currency"],
                event_id=payload["event_id"],
            )

    monkeypatch.setitem(ADAPTERS, "TEST_ACQUIRER", lambda **kwargs: CardAdapter(**kwargs))
    monkeypatch.setenv("TIBATRACE_TEST_CARD_KEY", "tenant-card-secret")
    monkeypatch.setenv(
        "TIBATRACE_CHECKOUT_CONNECTIONS",
        json.dumps(
            {
                str(world["tenant"].pk): {
                    "CARD": {
                        "enabled": True,
                        "validated": True,
                        "provider_code": "TEST_ACQUIRER",
                        "terminal_id": "CARD-TERM-01",
                        "terminals": {"POS-RETAIL-01": "CARD-TERM-01"},
                        "credentials_env": {"api_key": "TIBATRACE_TEST_CARD_KEY"},
                    }
                }
            }
        ),
    )
    draft = prepare_sale_for_payment(world)
    path = f"/api/pos/retail/transactions/{draft['id']}/checkout/"

    manual = world["client"].post(
        path,
        {
            "operation": "collect",
            "device_id": "POS-RETAIL-01",
            "tender_type": "CARD",
            "amount": "250",
            "reference": "MANUAL-REF",
            "idempotency_key": "card-manual-blocked",
        },
        format="json",
    )
    assert manual.status_code == 400
    assert not PaymentTender.all_objects.exists()

    initiated = world["client"].post(
        path,
        {
            "operation": "initiate",
            "device_id": "POS-RETAIL-01",
            "tender_type": "CARD",
            "amount": "250",
            "idempotency_key": "card-provider-01",
        },
        format="json",
    )
    assert initiated.status_code == 200, initiated.data
    assert initiated.data["intent"]["tenders"][0]["provider"] == "TEST_ACQUIRER"
    assert initiated.data["intent"]["tenders"][0]["status"] == (
        "SETTLED" if completion_path == "EARLY_CALLBACK" else "PENDING"
    )
    assert initiated.data["intent"]["amount_unallocated"] == "0.00"
    assert observed["context"] == {
        "currency": "KES",
        "device_id": "POS-RETAIL-01",
        "register_id": "RETAIL-01",
        "terminal_id": "CARD-TERM-01",
    }
    assert "tenant-card-secret" not in str(initiated.data)

    from apps.prescription.payment_services import PaymentSettlementService

    with pytest.raises(ValidationError, match="authenticated provider"):
        PaymentSettlementService.confirm_card(
            tender=PaymentTender.all_objects.get(provider="TEST_ACQUIRER"), approval_reference="FORGED-MANUAL",
            approved_amount=Decimal("250"), actor=world["operator"], idempotency_key="manual-bypass",
        )

    attempt = PaymentAttempt.all_objects.get(provider="TEST_ACQUIRER")
    if completion_path == "CALLBACK":
        assert callback(attempt, "forged").status_code == 202
        assert not PaymentSettlement.all_objects.exists()
        # An unauthenticated event must not reserve its event id and prevent
        # the provider's authentic redelivery from settling the payment.
        assert callback(attempt, "valid").status_code == 202
        assert callback(attempt, "valid").status_code == 202

    if completion_path == "CALLBACK":
        from apps.prescription.tasks import reconcile_checkout_providers

        reconcile_checkout_providers()
        reconciled = world["client"].get(path)
    else:
        reconciled = world["client"].post(
            path, {"operation": "query", "device_id": "POS-RETAIL-01"}, format="json"
        )
    assert reconciled.status_code == 200, reconciled.data
    assert reconciled.data["intent"]["status"] == "SETTLED"
    settlement = PaymentSettlement.all_objects.get(payment_tender__provider="TEST_ACQUIRER")
    assert settlement.source == ("PROVIDER_QUERY" if completion_path == "QUERY" else "PROVIDER_EVENT")
    assert reconciled.data["sale_state"] == "COMPLETED"
    assert RetailCashReceipt.all_objects.count() == 1
    replayed = world["client"].post(
        path, {"operation": "initiate", "device_id": "POS-RETAIL-01", "tender_type": "CARD",
               "amount": "250", "idempotency_key": "card-provider-01"}, format="json",
    )
    assert replayed.status_code == 200, replayed.data
    monkeypatch.setenv("TIBATRACE_CHECKOUT_CONNECTIONS", "{}")
    recovered = world["client"].post(
        path, {"operation": "initiate", "device_id": "POS-RETAIL-01", "tender_type": "CARD",
               "amount": "250", "idempotency_key": "card-provider-01"}, format="json",
    )
    assert recovered.status_code == 200, recovered.data
    assert observed["calls"] == 1


@pytest.mark.parametrize("outcome", ["TIMEOUT", "DECLINED", "UNKNOWN"])
def test_integrated_card_retains_original_request_through_provider_failure(world, monkeypatch, outcome):  # noqa: F811
    import json

    from tests.test_pos_payment_connections import StubCardAdapter

    from apps.prescription.payment_providers import ADAPTERS, InitiationResult

    calls = []

    class CardAdapter(StubCardAdapter):
        def initiate(self, *, attempt, context):  # noqa: ARG002
            calls.append(attempt.pk)
            if outcome == "TIMEOUT":
                raise TimeoutError("The remote outcome is unknown.")
            return InitiationResult(
                accepted=False, request_reference=attempt.request_reference,
                failure_code="DECLINED" if outcome == "DECLINED" else "UNKNOWN_OUTCOME",
            )

    monkeypatch.setitem(ADAPTERS, "TEST_ACQUIRER", CardAdapter)
    monkeypatch.setenv("TIBATRACE_CHECKOUT_CONNECTIONS", json.dumps({
        str(world["tenant"].pk): {"CARD": {"enabled": True, "validated": True, "provider_code": "TEST_ACQUIRER"}}
    }))
    draft = prepare_sale_for_payment(world)
    path = f"/api/pos/retail/transactions/{draft['id']}/checkout/"
    command = {"operation": "initiate", "device_id": "POS-RETAIL-01", "tender_type": "CARD",
               "amount": "250", "idempotency_key": "card-failure-01"}
    if outcome == "TIMEOUT":
        with pytest.raises(TimeoutError):
            world["client"].post(path, command, format="json")
    else:
        assert world["client"].post(path, command, format="json").status_code == 200
    attempt = PaymentAttempt.all_objects.get(provider="TEST_ACQUIRER")
    assert attempt.status == ("FAILED" if outcome == "DECLINED" else "STARTED")
    assert attempt.payment_tender.status == ("FAILED" if outcome == "DECLINED" else "PENDING")
    replayed = world["client"].post(path, command, format="json")
    assert replayed.status_code == 200, replayed.data
    assert replayed.data["intent"]["amount_unallocated"] == ("250.00" if outcome == "DECLINED" else "0.00")
    assert len(calls) == 1
    assert not PaymentSettlement.all_objects.exists()


def test_fiscal_is_separate_and_unconfigured_does_not_erase_payment(world):  # noqa: F811
    draft = prepare_sale_for_payment(world)
    response = collect(world, draft["id"], amount="250", received="300")
    assert response.status_code == 200, response.data
    assert response.data["intent"]["status"] == "SETTLED"
    assert response.data["fiscal"]["status"] == "NOT_CONFIGURED"
    sale = PosTransaction.all_objects.get(pk=draft["id"])
    row = FiscalService.enqueue(source=sale)
    FiscalService.submit(row)
    row.refresh_from_db()
    assert row.status == "NOT_CONFIGURED" and not row.response
    assert RetailCashReceipt.all_objects.filter(transaction=sale).exists()


def test_retail_checkout_allocates_only_one_fiscal_record(world):  # noqa: F811
    TenantEtimsProfile.all_objects.create(
        tenant=world["tenant"],
        is_enabled=True,
        tin="P051234567Z",
        bhf_id="00",
        dvc_srl_no="VSCU-NRB-001",
        auto_fiscalize_pos_sales=False,
    )
    draft = prepare_sale_for_payment(world)
    response = collect(world, draft["id"], amount="250", received="250")
    assert response.status_code == 200, response.data

    sale = PosTransaction.all_objects.get(pk=draft["id"])
    assert FiscalSubmission.all_objects.filter(
        tenant=world["tenant"], source_kind="RETAIL", source_id=sale.pk
    ).count() == 1
    assert not FiscalReceipt.all_objects.filter(
        tenant=world["tenant"], retail_cash_receipt__transaction=sale
    ).exists()


def test_fiscal_timeout_retains_invoice_and_never_automatically_resends(world, monkeypatch):  # noqa: F811
    draft = prepare_sale_for_payment(world)
    assert collect(world, draft["id"], amount="250", received="250").status_code == 200
    sale = PosTransaction.all_objects.get(pk=draft["id"])
    row = FiscalService.enqueue(source=sale)
    row.payload = {"invcNo": 7}
    row.invoice_number = 7
    row.payload_sha256 = "frozen"
    row.status = "QUEUED"
    row.save()
    monkeypatch.setattr("apps.prescription.fiscal.vscu_config", lambda **_: {"base_url": "http://127.0.0.1"})
    calls = []

    def timeout(payload):
        calls.append(payload)
        raise TimeoutError()

    FiscalService.submit(row, transport=timeout)
    row.refresh_from_db()
    assert row.status == "UNKNOWN"
    FiscalService.submit(row, transport=timeout)
    assert len(calls) == 1
    row.payload = {"invcNo": 8}
    with pytest.raises(ValidationError, match="immutable"):
        row.save()


def test_vscu_builds_one_itemized_invoice_and_accepts_only_receipt_evidence(world, monkeypatch):  # noqa: F811
    draft = prepare_sale_for_payment(world)
    assert collect(world, draft["id"], amount="250", received="250").status_code == 200
    sale = PosTransaction.all_objects.get(pk=draft["id"])
    row = FiscalService.enqueue(source=sale)
    config = {"tin": "TESTPIN001X", "bhf_id": "00", "base_url": "http://127.0.0.1", "tax_rates": {"A": 0},
              "items": {str(world["sku"].pk): {"item_code": "TEST001", "classification_code": "1234567890", "package_unit": "PK", "quantity_unit": "U", "tax_type": "A"}}}
    monkeypatch.setattr("apps.prescription.fiscal.vscu_config", lambda **_: config)
    sent = []
    def transport(payload):
        sent.append(payload)
        return {"resultCd": "000", "data": {"rcptNo": 10, "rcptSign": "TEST-SIGNATURE", "intrlData": "TEST-INTERNAL", "sdcId": "TEST-VSCU"}}
    FiscalService.submit(row, transport=transport)
    row.refresh_from_db()
    assert row.status == "ACCEPTED" and row.payload["totAmt"] == "250.00"
    assert row.payload["totItemCnt"] == 1 and row.payload["itemList"][0]["qty"] == "2.0000"
    FiscalService.submit(row, transport=transport)
    assert len(sent) == 1
    assert FiscalService.status(sale)["receipt"]["rcptSign"] == "TEST-SIGNATURE"


def test_till_cannot_close_while_a_split_is_partly_settled(world):  # noqa: F811
    from apps.pos_shift.reporting import ShiftReportService
    draft = prepare_sale_for_payment(world)
    assert collect(world, draft["id"]).status_code == 200
    problems = ShiftReportService.check_closure_preconditions(session=world["session"])
    assert any(item["code"] == "PAYMENTS_UNRESOLVED" and item["waivable"] is False for item in problems)


def test_clinical_split_preserves_the_supply_gate_until_full_settlement(domain):  # noqa: F811
    from tests.test_pos_enterprise_dispensing import make_clinically_ready

    from apps.prescription.checkout import CheckoutService
    from apps.prescription.models import DispensingEpisode
    make_clinically_ready(domain)
    episode = domain["episode"]
    episode.status = "READY_FOR_PAYMENT"
    episode.save(update_fields=["status"])
    due = episode.sales_order.total
    assert due > 1
    part = due / 2
    data = CheckoutService.collect(source=episode, actor=domain["cashier"], device_id=domain["device_id"], tender_type="CASH",
        amount=part, cash_received=part, reference="", idempotency_key="clinical-part-1")
    assert data["intent"]["status"] == "PARTIALLY_SETTLED"
    episode.refresh_from_db()
    assert episode.payment_state == "PARTIALLY_PAID" and episode.status == "READY_FOR_PAYMENT"
    data = CheckoutService.collect(source=episode, actor=domain["cashier"], device_id=domain["device_id"], tender_type="CARD",
        amount=due-part, cash_received=Decimal("0"), reference="TERM-CLINICAL", idempotency_key="clinical-part-2")
    assert data["intent"]["status"] == "SETTLED"
    assert DispensingEpisode.all_objects.get(pk=episode.pk).payment_state == "PAID"


def test_split_refund_preserves_original_methods_and_drawer_cash(world):  # noqa: F811
    from tests.test_retail_refunds import approve, refund_request
    draft = prepare_sale_for_payment(world)
    assert collect(world, draft['id'], amount='100', received='100').status_code == 200
    assert collect(world, draft['id'], amount='150', received='0', method='CARD', key='card-part', reference='SALE-APPROVAL').status_code == 200
    sale = world['client'].get(f"/api/pos/retail/transactions/{draft['id']}/").json()
    requested, _ = refund_request(world, sale, quantity='2')
    assert requested.status_code == 201, requested.data
    refund = requested.json()
    assert [(part['tender_type'], Decimal(part['amount'])) for part in refund['payment_plan']] == [('CASH', Decimal('100')), ('CARD', Decimal('150'))]
    approve(world, sale, refund)
    path = f"/api/pos/retail/transactions/{sale['id']}/cash-refund/"
    command = {'refund_request_id': refund['id'], 'device_id': 'POS-RETAIL-01', 'idempotency_key': 'split-refund'}
    assert world['client'].post(path, command, format='json').status_code == 400
    card = next(part for part in refund['payment_plan'] if part['tender_type'] == 'CARD')
    command['payment_references'] = {card['tender_id']: 'TERMINAL-REFUND-01'}
    response = world['client'].post(path, command, format='json')
    assert response.status_code == 200, response.data
    assert Decimal(response.data['cash_amount']) == Decimal('100')
    breakdown = CashControlService.tender_breakdown(session=world['session'])
    assert breakdown.cash == 0 and breakdown.non_cash == 0
    assert CashControlService.expected_cash(session=world['session']).cash_refunds == 100
    assert world['client'].post(path, command, format='json').status_code == 200
    command['payment_references'][card['tender_id']] = 'CHANGED-REF'
    assert world['client'].post(path, command, format='json').status_code == 400


def test_retail_ledger_cannot_be_mutated_through_legacy_endpoint(world):  # noqa: F811
    draft = prepare_sale_for_payment(world)
    assert collect(world, draft['id']).status_code == 200
    tender = PaymentTender.all_objects.first()
    response = world['client'].post(f'/api/pos/payments/tenders/{tender.pk}/card-confirm/',
        {'approval_reference': 'BYPASS', 'approved_amount': '150', 'idempotency_key': 'bypass'}, format='json')
    assert response.status_code in {400, 403, 404}
    assert PaymentSettlement.all_objects.count() == 1


def test_unfinished_cash_payment_void_needs_independent_supervisor_and_releases_stock(world):  # noqa: F811
    from tests.test_retail_refunds import user

    from apps.inventory.models import InventoryLedgerEntry
    from apps.pos_shift.models import OperatorShift
    from apps.prescription.checkout_void import CheckoutVoidService
    draft = prepare_sale_for_payment(world)
    assert collect(world, draft['id']).status_code == 200
    sale = PosTransaction.all_objects.get(pk=draft['id'])
    CheckoutVoidService.run(source=sale, actor=world['operator'], device_id='POS-RETAIL-01', approve=False, reason='Customer cancelled before completion', references={})
    assert collect(world, draft['id'], amount='150', received='150', key='late-money').status_code == 400
    with pytest.raises(ValidationError, match='different authorised supervisor'):
        CheckoutVoidService.run(source=sale, actor=world['operator'], device_id='POS-RETAIL-01', approve=True, reason='', references={})
    supervisor = user(world['tenant'], 'void-supervisor', ['pos.refund.approve'])
    OperatorShift.all_objects.filter(tenant=world['tenant'], register_session=world['session'], state='OPEN').update(state='CLOSED')
    OperatorShift.all_objects.create(tenant=world['tenant'], register_session=world['session'], operator=supervisor, state='OPEN')
    CheckoutVoidService.run(source=sale, actor=supervisor, device_id='POS-RETAIL-01', approve=True, reason='', references={})
    sale.refresh_from_db()
    assert sale.state == 'VOIDED'
    assert not InventoryReservation.all_objects.filter(source_document=str(sale.pk), status='ALLOCATED').exists()
    assert not InventoryLedgerEntry.all_objects.filter(source_document_type='POS_RETAIL_TRANSACTION', source_document_id=str(sale.pk), entry_type='ISSUE').exists()
    assert CashControlService.tender_breakdown(session=world['session']).cash == 0


def test_vscu_credit_note_links_original_invoice_and_keeps_refund_separate(world, monkeypatch):  # noqa: F811
    from tests.test_retail_refunds import approve, execute, refund_request
    draft = prepare_sale_for_payment(world)
    assert collect(world, draft['id'], amount='250', received='250').status_code == 200
    sale = PosTransaction.all_objects.get(pk=draft['id'])
    config = {'tin': 'TESTPIN001X', 'bhf_id': '00', 'base_url': 'http://127.0.0.1', 'tax_rates': {'A': 0},
              'items': {str(world['sku'].pk): {'item_code': 'TEST001', 'classification_code': '1234567890', 'package_unit': 'PK', 'quantity_unit': 'U', 'tax_type': 'A'}}}
    monkeypatch.setattr('apps.prescription.fiscal.vscu_config', lambda **_: config)
    original = FiscalService.enqueue(source=sale)
    def response(payload):
        return {'resultCd': '000', 'data': {'rcptNo': payload['invcNo'], 'rcptSign': 'TEST-SIGN', 'intrlData': 'TEST-INTERNAL', 'sdcId': 'TEST-VSCU'}}
    FiscalService.submit(original, transport=response)
    original.refresh_from_db()
    detail = world['client'].get(f"/api/pos/retail/transactions/{sale.pk}/").json()
    requested, _ = refund_request(world, detail)
    assert requested.status_code == 201, requested.data
    approve(world, detail, requested.json())
    completed = execute(world, detail, requested.json())
    assert completed.status_code == 200, completed.data
    from apps.pos_transactions.models import RetailCashRefund
    from apps.prescription.pos_printing_models import PosPrintDocument
    refund = RetailCashRefund.all_objects.get(pk=completed.data['id'])
    credit = FiscalService.enqueue(source=refund)
    FiscalService.submit(credit, transport=response)
    credit.refresh_from_db()
    assert credit.status == 'ACCEPTED'
    assert credit.payload['orgInvcNo'] == original.invoice_number
    assert credit.payload['rcptTyCd'] == 'R' and credit.payload['salesSttsCd'] == '05'
    assert Decimal(credit.payload['totAmt']) == Decimal('125')
    assert PosPrintDocument.all_objects.filter(document_type='FISCAL_CREDIT_NOTE').count() == 1
    assert sale.state == 'COMPLETED'
