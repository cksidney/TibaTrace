from rest_framework import serializers

from apps.customers.models import Customer, CustomerCommercialProfile, CustomerDeliveryAddress


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = "__all__"
        read_only_fields = ("id", "status", "approved_at", "approved_by", "created_at", "updated_at")


class CustomerDeliveryAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerDeliveryAddress
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at")


class CustomerCommercialProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerCommercialProfile
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at")
