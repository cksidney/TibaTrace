from django.urls import path

from .views import FiscalReceiptDetailView, FiscalReceiptListView, FiscalReceiptRetryView, TenantEtimsProfileView

urlpatterns = [
    path("profile/", TenantEtimsProfileView.as_view(), name="etims-profile"),
    path("receipts/", FiscalReceiptListView.as_view(), name="fiscal-receipt-list"),
    path("receipts/<uuid:pk>/", FiscalReceiptDetailView.as_view(), name="fiscal-receipt-detail"),
    path("receipts/<uuid:pk>/retry/", FiscalReceiptRetryView.as_view(), name="fiscal-receipt-retry"),
]
