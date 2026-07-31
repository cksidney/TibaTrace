from .base import *

DEBUG = True
FHIR_WRITE_INTERACTIONS_ENABLED = True
CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:3009",
    "http://localhost:3009",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]
