from rest_framework import serializers

from apps.customers.models import Customer, CustomerCommercialProfile, CustomerDeliveryAddress


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = "__all__"
        read_only_fields = (
            "id",
            "tenant",
            "status",
            "created_by",
            "approved_at",
            "approved_by",
            "created_at",
            "updated_at",
        )

    def validate_customer_number(self, value):
        customer_number = value.strip().upper()
        if not customer_number:
            raise serializers.ValidationError("Customer number is required.")
        return customer_number

    def validate_legal_name(self, value):
        legal_name = value.strip()
        if not legal_name:
            raise serializers.ValidationError("Legal name is required.")
        return legal_name


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
