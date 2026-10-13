# ruff: noqa: F811
import pytest
from rest_framework.test import APIClient
from tests.test_pos_enterprise_dispensing import domain, make_clinically_ready, setup_domain  # noqa: F401
from tests.test_pos_printing import settle_episode

from apps.identity.models import User
from apps.prescription.models import PosLabelReprintAudit
from apps.prescription.pos_printing_models import PosPrintJob

pytestmark = pytest.mark.django_db


def api(user):
    client = APIClient()
    client.force_login(user)
    return client


def test_physical_transport_is_device_bound_and_does_not_claim_paper_output(domain):
    episode, _ = settle_episode(domain)
    job = PosPrintJob.all_objects.get(document__episode=episode)
    client = api(domain["pharmacist"])
    base = f"/api/pos/dispensing/print-jobs/{job.pk}/"
    assert client.post(f"{base}snapshot/", {"device_id": "WRONG-DEVICE"}, format="json").status_code == 403
    document = client.post(f"{base}snapshot/", {"device_id": domain["device_id"]}, format="json")
    assert document.status_code == 200
    assert document.json()["document_hash"] == job.document.document_hash
    assert client.post(f"{base}select-transport/", {
        "device_id": domain["device_id"], "transport": "WINDOWS_SPOOLER", "printer": "Manager USB printer",
    }, format="json").status_code == 200
    assert client.post(f"{base}start/", {}, format="json").status_code == 200
    job.refresh_from_db()
    assert job.status == "SENDING"
    assert job.printed_at is None
    assert client.post(f"{base}select-transport/", {
        "device_id": domain["device_id"], "transport": "WINDOWS_SPOOLER", "printer": "Another printer",
    }, format="json").status_code == 400
    assert client.post(f"{base}result/", {"succeeded": True}, format="json").status_code == 200
    job.refresh_from_db()
    assert job.printed_by_id == domain["pharmacist"].pk
    assert job.attempt_count == 1


def test_no_print_capability_cannot_read_document_contents(domain):
    episode, _ = settle_episode(domain)
    job = PosPrintJob.all_objects.get(document__episode=episode)
    user = User.objects.create_user(username="no-print-cap", tenant=domain["tenant"])
    response = api(user).post(f"/api/pos/dispensing/print-jobs/{job.pk}/snapshot/",
        {"device_id": domain["device_id"]}, format="json")
    assert response.status_code == 403


def test_medicine_label_is_queued_once_and_physical_output_has_governed_audit(domain):
    make_clinically_ready(domain)
    client = api(domain["pharmacist"])
    episode = domain["episode"]
    path = f"/api/pos/dispensing/episodes/{episode.pk}/label/"
    body = {"dispensing_line_id": str(domain["line"].pk), "device_id": domain["device_id"]}
    first = client.post(path, body, format="json")
    assert first.status_code == 200, first.data
    replay = client.post(path, body, format="json")
    assert replay.status_code == 200, replay.data
    assert replay.json()["print_job_id"] == first.json()["print_job_id"]
    job = PosPrintJob.all_objects.get(pk=first.json()["print_job_id"])
    assert job.document.snapshot["label"]["medicine_name"] == domain["sku"].display_name
    assert job.document.snapshot["label"]["directions"] == domain["line"].dosage_label_instructions
    assert PosPrintJob.all_objects.filter(document__label_id=first.json()["label_id"]).count() == 1
    base = f"/api/pos/dispensing/print-jobs/{job.pk}/"
    assert client.post(f"{base}start/", {}, format="json").status_code == 200
    assert PosLabelReprintAudit.all_objects.filter(label_id=job.document.label_id).count() == 0
    assert client.post(f"{base}result/", {"succeeded": True}, format="json").status_code == 200
    assert PosLabelReprintAudit.all_objects.get(label_id=job.document.label_id).is_original is True
