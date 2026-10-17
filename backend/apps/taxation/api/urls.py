from django.urls import path

from apps.taxation.api.views import (
    EtimsInitializeView,
    EtimsTestConnectionView,
    FiscalReceiptDetailView,
    FiscalReceiptListView,
    FiscalReceiptRetryView,
    TenantEtimsProfileView,
)

urlpatterns = [
    path("profile/", TenantEtimsProfileView.as_view(), name="etims-profile"),
    path("test-connection/", EtimsTestConnectionView.as_view(), name="etims-test-connection"),
    path("initialize/", EtimsInitializeView.as_view(), name="etims-initialize"),
    path("receipts/", FiscalReceiptListView.as_view(), name="fiscal-receipt-list"),
    path("receipts/<uuid:pk>/", FiscalReceiptDetailView.as_view(), name="fiscal-receipt-detail"),
    path("receipts/<uuid:pk>/retry/", FiscalReceiptRetryView.as_view(), name="fiscal-receipt-retry"),
]
