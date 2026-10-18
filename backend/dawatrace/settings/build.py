"""Static asset compilation only; the shipped runtime uses production settings."""

from .base import *

DEBUG = False
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
