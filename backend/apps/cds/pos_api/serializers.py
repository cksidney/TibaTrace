from rest_framework import serializers

from apps.cds.pos_screening_models import (
    PosClinicalDecision,
    PosClinicalFinding,
    PosClinicalOverride,
    PosClinicalScreening,
)


class PosClinicalBasketLineSerializer(serializers.Serializer):
    line_id = serializers.CharField(required=False, allow_blank=True)
    commercial_sku_id = serializers.CharField(required=False, allow_blank=True)
    clinical_medicinal_product_id = serializers.CharField(required=False, allow_blank=True)
    manufactured_medicinal_product_id = serializers.CharField(required=False, allow_blank=True)
    active_ingredient_ids = serializers.ListField(child=serializers.CharField(), required=False)
    prescription_item_id = serializers.CharField(required=False, allow_blank=True)
    medicine_name = serializers.CharField(required=True)
    strength = serializers.CharField(required=False, allow_blank=True)
    dosage_form = serializers.CharField(required=False, allow_blank=True)
    route = serializers.CharField(required=False, allow_blank=True)
    quantity = serializers.IntegerField(required=True, min_value=1)
    dose_instructions = serializers.CharField(required=False, allow_blank=True)
    dose_value = serializers.CharField(required=False, allow_blank=True)
    dose_unit = serializers.CharField(required=False, allow_blank=True)
    frequency_per_day = serializers.CharField(required=False, allow_blank=True)
    duration_days = serializers.CharField(required=False, allow_blank=True)
    is_controlled = serializers.BooleanField(required=False, allow_null=True)
    is_prescription_only = serializers.BooleanField(required=False, allow_null=True)
    batch_id = serializers.CharField(required=False, allow_blank=True)
    batch_number = serializers.CharField(required=False, allow_blank=True)
    batch_expiry_date = serializers.DateField(required=False, allow_null=True)
    batch_recalled = serializers.BooleanField(required=False, allow_null=True)

class PosClinicalScreeningRequestSerializer(serializers.Serializer):
    transaction_id = serializers.CharField(required=True)
    device_id = serializers.CharField(required=True)
    register_id = serializers.CharField(required=False, allow_blank=True)
    patient_id = serializers.UUIDField(required=False, allow_null=True)
    prescription_id = serializers.UUIDField(required=False, allow_null=True)
    dispensing_episode_id = serializers.CharField(required=False, allow_blank=True)
    basket_lines = serializers.ListField(
        child=PosClinicalBasketLineSerializer(), min_length=1
    )
    context_hash = serializers.CharField(required=False, allow_blank=True)
    client_screened_at = serializers.DateTimeField(required=False, allow_null=True)
    offline_state = serializers.BooleanField(required=False, default=False)

class PosClinicalFindingSerializer(serializers.ModelSerializer):
    rule_id = serializers.ReadOnlyField(source='rule.id')

    class Meta:
        model = PosClinicalFinding
        fields = '__all__'

class PosClinicalScreeningResultSerializer(serializers.ModelSerializer):
    findings = PosClinicalFindingSerializer(many=True, read_only=True)
    screening_id = serializers.UUIDField(read_only=True)
    blocking_findings = serializers.IntegerField(source='blocking_count', read_only=True)
    status = serializers.CharField(source='screening_status', read_only=True)

    class Meta:
        model = PosClinicalScreening
        fields = [
            'id', 'screening_id', 'transaction_id', 'device_id', 'register_id',
            'patient', 'prescription', 'dispensing_episode_id', 'context_hash',
            'status', 'highest_severity', 'blocking_findings', 'requires_pharmacist',
            'safe_to_proceed', 'rule_set_version', 'evaluated_at', 'expires_at',
            'cashier', 'offline_state', 'idempotency_key', 'created_at', 'updated_at',
            'findings'
        ]

class PosClinicalAcknowledgementSerializer(serializers.Serializer):
    finding_id = serializers.UUIDField(required=True)
    cashier_id = serializers.CharField(required=False, allow_blank=True)
    #: The context the client believes it is acting on. The server refuses
    #: the write if the basket has moved on since.
    expected_context_hash = serializers.CharField(max_length=64)

class PosPharmacistReviewRequestSerializer(serializers.Serializer):
    cashier_id = serializers.CharField(required=True)
    urgency_note = serializers.CharField(required=False, allow_blank=True)
    #: The context the client believes it is acting on. The server refuses
    #: the write if the basket has moved on since.
    expected_context_hash = serializers.CharField(max_length=64)

class PosPharmacistDecisionSerializer(serializers.Serializer):
    finding_id = serializers.UUIDField(required=False, allow_null=True)
    pharmacist_id = serializers.CharField(required=False, allow_blank=True)
    auth_method = serializers.CharField(required=False, allow_blank=True)
    decision = serializers.ChoiceField(choices=PosClinicalDecision.Decision.choices, required=True)
    clinical_justification = serializers.CharField(required=False, allow_blank=True)
    counselling_notes = serializers.CharField(required=False, allow_blank=True)
    prescriber_contact_ref = serializers.CharField(required=False, allow_blank=True)
    override_reason = serializers.ChoiceField(choices=PosClinicalOverride.OverrideReason.choices, required=False, allow_blank=True, allow_null=True)
    idempotency_key = serializers.CharField(required=True)
    #: The context the client believes it is acting on. The server refuses
    #: the write if the basket has moved on since.
    expected_context_hash = serializers.CharField(max_length=64)

class PosClinicalOverrideSerializer(serializers.Serializer):
    finding_id = serializers.UUIDField(required=True)
    pharmacist_id = serializers.CharField(required=False, allow_blank=True)
    override_reason = serializers.ChoiceField(choices=PosClinicalOverride.OverrideReason.choices, required=True)
    clinical_justification = serializers.CharField(required=True)
    override_capability = serializers.CharField(required=True)
    idempotency_key = serializers.CharField(required=True)
    #: The context the client believes it is acting on. The server refuses
    #: the write if the basket has moved on since.
    expected_context_hash = serializers.CharField(max_length=64)
