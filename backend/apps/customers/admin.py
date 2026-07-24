from django.contrib import admin

from apps.customers.models import Customer, CustomerCommercialProfile, CustomerDeliveryAddress


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("customer_number", "legal_name", "customer_type", "status", "credit_status")
    search_fields = ("customer_number", "legal_name")


@admin.register(CustomerDeliveryAddress)
class CustomerDeliveryAddressAdmin(admin.ModelAdmin):
    list_display = ("address_code", "recipient_name", "city", "customer", "is_active")
    search_fields = ("address_code", "recipient_name", "customer__legal_name")


@admin.register(CustomerCommercialProfile)
class CustomerCommercialProfileAdmin(admin.ModelAdmin):
    list_display = ("customer", "credit_limit", "payment_terms", "tax_treatment")
    search_fields = ("customer__legal_name", "customer__customer_number")
