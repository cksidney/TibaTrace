"""DHA queue maintenance; tenant activation is checked again before dispatch."""
from io import StringIO

from celery import shared_task
from django.core.management import call_command


@shared_task
def process_dha_exchanges():
    call_command("process_dha_exchanges", limit=50, stdout=StringIO())
    return {"completed": True}
