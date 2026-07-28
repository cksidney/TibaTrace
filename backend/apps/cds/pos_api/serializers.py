from rest_framework import serializers

from apps.cds.pos_screening_models import (
    PosClinicalDecision,
    PosClinicalFinding,
    PosClinicalOverride,
    PosClinicalScreening,
)


class PosClinicalBasketLineSerializer(serializers.Serializer):
    line_id = serializers.CharField(required=False, allow_blank=True)
    sku_id = serializers.CharField(required=False, allow_blank=True)
    clinical_product_id = serializers.CharField(required=False, allow_blank=True)
    commercial_sku_id = serializers.CharField(required=False, allow_blank=True)
    clinical_medicinal_product_id = serializers.CharField(required=False, allow_blank=True)
    manufactured_medicinal_product_id = serializers.CharField(required=False, allow_blank=True)
    active_ingredient_ids = serializers.ListField(child=serializers.CharField(), required=False)
    prescription_item_id = serializers.CharField(required=False, allow_blank=True)
    medicine_name = serializers.CharField(required=False, allow_blank=True, default="")
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

    def validate(self, attrs):
        attrs["sku_id"] = attrs.get("sku_id") or attrs.get("commercial_sku_id", "")
        attrs["clinical_product_id"] = (
            attrs.get("clinical_product_id") or attrs.get("clinical_medicinal_product_id", "")
        )
        return attrs

class PosClinicalScreeningRequestSerializer(serializers.Serializer):
    transaction_id = serializers.CharField(required=True)
    device_id = serializers.CharField(required=True)
    register_id = serializers.CharField(required=False, allow_blank=True)
    branch_id = serializers.UUIDField(required=False, allow_null=True)
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


class PosClinicalDecisionHistorySerializer(serializers.ModelSerializer):
    pharmacist_id = serializers.UUIDField(read_only=True)
    pharmacist_name = serializers.SerializerMethodField()
    finding_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = PosClinicalDecision
        fields = [
            'id', 'finding_id', 'pharmacist_id', 'pharmacist_name', 'decision',
            'clinical_justification', 'conditions', 'counselling_notes',
            'prescriber_contact_ref', 'follow_up_actions', 'context_hash_at_decision',
            'rule_version_at_decision', 'branch_id', 'transaction_id', 'register_id',
            'patient_ref', 'prescription_ref', 'created_at',
        ]

    def get_pharmacist_name(self, decision):
        return decision.pharmacist.get_full_name() or decision.pharmacist.get_username()

class PosClinicalScreeningResultSerializer(serializers.ModelSerializer):
    findings = PosClinicalFindingSerializer(many=True, read_only=True)
    decisions = PosClinicalDecisionHistorySerializer(many=True, read_only=True)
    screening_id = serializers.UUIDField(read_only=True)
    blocking_findings = serializers.IntegerField(source='blocking_count', read_only=True)

    class Meta:
        model = PosClinicalScreening
        fields = [
            'id', 'screening_id', 'transaction_id', 'device_id', 'register_id', 'branch_id',
            'patient', 'prescription', 'dispensing_episode_id', 'context_hash',
            'status', 'highest_severity', 'blocking_findings', 'requires_pharmacist',
            'safe_to_proceed', 'rule_set_version', 'evaluated_at', 'expires_at',
            'cashier', 'offline_state', 'idempotency_key', 'created_at', 'updated_at',
            'findings', 'decisions'
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
    finding_id = serializers.UUIDField(required=True)
    pharmacist_id = serializers.CharField(required=False, allow_blank=True)
    auth_method = serializers.CharField(required=False, allow_blank=True)
    decision = serializers.ChoiceField(choices=PosClinicalDecision.Decision.choices, required=True)
    clinical_justification = serializers.CharField(required=True, allow_blank=False, trim_whitespace=True)
    conditions = serializers.CharField(required=False, allow_blank=True)
    counselling_notes = serializers.CharField(required=False, allow_blank=True)
    prescriber_contact_ref = serializers.CharField(required=False, allow_blank=True)
    follow_up_actions = serializers.CharField(required=False, allow_blank=True)
    override_reason = serializers.ChoiceField(choices=PosClinicalOverride.OverrideReason.choices, required=False, allow_blank=True, allow_null=True)
    idempotency_key = serializers.CharField(required=True)
    #: The context the client believes it is acting on. The server refuses
    #: the write if the basket has moved on since.
    expected_context_hash = serializers.CharField(max_length=64)

    def validate(self, attrs):
        if (
            attrs['decision'] == PosClinicalDecision.Decision.APPROVE_WITH_CONDITIONS
            and not attrs.get('conditions', '').strip()
        ):
            raise serializers.ValidationError(
                {'conditions': 'Approval with conditions requires the conditions to be recorded.'}
            )
        return attrs

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
