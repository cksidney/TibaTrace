from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.cds.models import ActiveIngredient, ClinicalKnowledgeRelease, ClinicalKnowledgeRule
from apps.cds.pos_screening_services import PosClinicalScreeningService
from apps.identity.models import User
from apps.medicines.models import (
    ActiveSubstance,
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    IngredientComposition,
    ManufacturedMedicinalProduct,
    PackageDefinition,
)
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Seed POS clinical screening data for demo."

    def handle(self, *args, **options):
        tenant = Tenant.objects.first()
        if not tenant:
            tenant = Tenant.objects.create(name="Demo Tenant", slug="demo")

        cashier, _ = User.objects.get_or_create(username="demo_cashier", defaults={"tenant": tenant})
        pharmacist, _ = User.objects.get_or_create(username="demo_pharmacist", defaults={"tenant": tenant})

        release, _ = ClinicalKnowledgeRelease.all_objects.get_or_create(
            tenant=tenant,
            code="DEMO-RELEASE",
            defaults={
                "version": "1.0",
                "source": "DEMO",
                "source_version": "1.0",
                "licence": "INTERNAL",
                "checksum_sha256": "0" * 64,
                "effective_date": date.today(),
                "is_active": True,
            },
        )

        ing_otc, _ = ActiveIngredient.all_objects.get_or_create(tenant=tenant, code="ING-OTC", name="OTC Ingredient")
        sub_otc, _ = ActiveSubstance.all_objects.get_or_create(
            tenant=tenant, code="ING-OTC", defaults={"canonical_name": "OTC Ingredient", "display_name": "OTC Ingredient", "search_name": "otc ingredient"}
        )
        
        ing_a, _ = ActiveIngredient.all_objects.get_or_create(tenant=tenant, code="ING-A", name="Ingredient A")
        sub_a, _ = ActiveSubstance.all_objects.get_or_create(
            tenant=tenant, code="ING-A", defaults={"canonical_name": "Ingredient A", "display_name": "Ingredient A", "search_name": "ingredient a"}
        )
        
        ing_b, _ = ActiveIngredient.all_objects.get_or_create(tenant=tenant, code="ING-B", name="Ingredient B")
        sub_b, _ = ActiveSubstance.all_objects.get_or_create(
            tenant=tenant, code="ING-B", defaults={"canonical_name": "Ingredient B", "display_name": "Ingredient B", "search_name": "ingredient b"}
        )

        dose_form, _ = DoseForm.objects.get_or_create(code="TAB", name="Tablet")

        def create_med(code, substance, controlled="NONE"):
            prod, created = ClinicalMedicinalProduct.all_objects.get_or_create(
                tenant=tenant,
                code=code,
                defaults={
                    "canonical_name": f"Product {code}",
                    "dose_form": dose_form,
                    "status": "ACTIVE",
                    "controlled_classification": controlled,
                },
            )
            if created:
                IngredientComposition.objects.create(
                    clinical_product=prod,
                    active_substance=substance,
                    numerator_value=Decimal("500"),
                    numerator_unit="mg",
                )

            mmp, _ = ManufacturedMedicinalProduct.all_objects.get_or_create(
                tenant=tenant,
                code=f"MMP-{code}",
                defaults={"brand_name": f"Brand {code}", "clinical_product": prod, "status": "ACTIVE"},
            )
            pkg, _ = PackageDefinition.objects.get_or_create(
                code=f"PACK-{code}", defaults={"description": "Pack", "unit_of_measure": "TABLET", "is_dispensing_unit": True}
            )
            sku, _ = CommercialSKU.all_objects.get_or_create(
                tenant=tenant,
                sku_code=f"SKU-{code}",
                defaults={"display_name": f"SKU {code}", "manufactured_product": mmp, "package_definition": pkg, "status": "ACTIVE"},
            )
            return sku

        sku_otc = create_med("MED-OTC", sub_otc)
        sku_a = create_med("MED-A", sub_a)
        sku_b = create_med("MED-B", sub_b)

        # Rules
        ClinicalKnowledgeRule.all_objects.get_or_create(
            tenant=tenant,
            release=release,
            rule_id="DD-INFO",
            rule_version="1.0",
            defaults={
                "rule_type": "DRUG_DRUG",
                "primary_code": "ING-OTC",
                "interacting_code": "ING-A",
                "severity": "LOW",
                "evidence_summary": "Low interaction evidence",
                "explanation": "Minor interaction between OTC and A",
                "recommended_action": "Inform patient",
                "effective_date": date.today(),
                "is_active": True,
            },
        )
        ClinicalKnowledgeRule.all_objects.get_or_create(
            tenant=tenant,
            release=release,
            rule_id="DD-HIGH",
            rule_version="1.0",
            defaults={
                "rule_type": "DRUG_DRUG",
                "primary_code": "ING-A",
                "interacting_code": "ING-B",
                "severity": "HIGH",
                "evidence_summary": "High interaction evidence",
                "explanation": "Severe interaction between A and B",
                "recommended_action": "Pharmacist intervention required",
                "effective_date": date.today(),
                "is_active": True,
            },
        )

        def eval_basket(tx_id, lines):
            PosClinicalScreeningService.evaluate(
                tenant=tenant, transaction_id=tx_id, device_id="dev-demo", basket_lines=lines, cashier=cashier
            )

        # 1. No interaction
        eval_basket("tx-demo-1", [{"line_id": "1", "sku_id": str(sku_otc.id), "quantity": "1"}])
        # 2. Low-severity
        eval_basket("tx-demo-2", [{"line_id": "1", "sku_id": str(sku_otc.id), "quantity": "1"}, {"line_id": "2", "sku_id": str(sku_a.id), "quantity": "1"}])
        # 3. High interaction
        eval_basket("tx-demo-3", [{"line_id": "1", "sku_id": str(sku_a.id), "quantity": "1"}, {"line_id": "2", "sku_id": str(sku_b.id), "quantity": "1"}])

        self.stdout.write(self.style.SUCCESS("Successfully seeded POS clinical screening demo data."))
