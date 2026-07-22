import decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.medicines.models import (
    ActiveSubstance,
    AdministrationRoute,
    BranchAssortment,
    ClinicalMedicinalProduct,
    CommercialSKU,
    DoseForm,
    IngredientComposition,
    ManufacturedMedicinalProduct,
    Manufacturer,
    PackageDefinition,
    ProductIdentifier,
    SubstitutionGroup,
    SubstitutionPolicy,
)
from apps.organizations.models import Location
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Seed deterministic enterprise medicine catalogue & product master data."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Seeding enterprise medicine catalogue...")

        # 1. Dose Forms
        dose_forms_data = [
            ("TAB", "Tablet"),
            ("CAP", "Capsule"),
            ("SUSP", "Oral Suspension"),
            ("SYR", "Syrup"),
            ("INJ", "Injection"),
            ("CREAM", "Cream"),
            ("OINT", "Ointment"),
            ("INH", "Inhaler"),
            ("SUPP", "Suppository"),
            ("DROPS", "Eye Drops"),
        ]
        dose_forms = {}
        for code, name in dose_forms_data:
            df, _ = DoseForm.objects.get_or_create(code=code, defaults={"name": name})
            dose_forms[code] = df

        # 2. Administration Routes
        routes_data = [
            ("PO", "Oral"),
            ("IV", "Intravenous"),
            ("IM", "Intramuscular"),
            ("TOP", "Topical"),
            ("OPH", "Ophthalmic"),
            ("INH", "Inhalation"),
            ("REC", "Rectal"),
            ("SC", "Subcutaneous"),
            ("SL", "Sublingual"),
            ("NAS", "Nasal"),
        ]
        routes = {}
        for code, name in routes_data:
            rt, _ = AdministrationRoute.objects.get_or_create(code=code, defaults={"name": name})
            routes[code] = rt

        # 3. Active Substances (20)
        substances_data = [
            ("SUB-PAR", "Paracetamol", "Paracetamol", "CHEMICAL", "NONE"),
            ("SUB-AMO", "Amoxicillin", "Amoxicillin", "CHEMICAL", "NONE"),
            ("SUB-CLA", "Clavulanic Acid", "Clavulanic Acid", "CHEMICAL", "NONE"),
            ("SUB-MET", "Metformin Hydrochloride", "Metformin Hydrochloride", "CHEMICAL", "NONE"),
            ("SUB-IBU", "Ibuprofen", "Ibuprofen", "CHEMICAL", "NONE"),
            ("SUB-SAL", "Salbutamol", "Salbutamol", "CHEMICAL", "NONE"),
            ("SUB-OME", "Omeprazole", "Omeprazole", "CHEMICAL", "NONE"),
            ("SUB-CEF", "Ceftriaxone", "Ceftriaxone", "CHEMICAL", "NONE"),
            ("SUB-DIC", "Diclofenac Sodium", "Diclofenac Sodium", "CHEMICAL", "NONE"),
            ("SUB-CIP", "Ciprofloxacin", "Ciprofloxacin", "CHEMICAL", "NONE"),
            ("SUB-AZI", "Azithromycin", "Azithromycin", "CHEMICAL", "NONE"),
            ("SUB-LOS", "Losartan Potassium", "Losartan Potassium", "CHEMICAL", "NONE"),
            ("SUB-AML", "Amlodipine Besylate", "Amlodipine Besylate", "CHEMICAL", "NONE"),
            ("SUB-ATOR", "Atorvastatin Calcium", "Atorvastatin Calcium", "CHEMICAL", "NONE"),
            ("SUB-DEX", "Dexamethasone", "Dexamethasone", "CHEMICAL", "NONE"),
            ("SUB-MOR", "Morphine Sulfate", "Morphine Sulfate", "CHEMICAL", "SCHEDULE_2"),
            ("SUB-COD", "Codeine Phosphate", "Codeine Phosphate", "CHEMICAL", "SCHEDULE_3"),
            ("SUB-DIA", "Diazepam", "Diazepam", "CHEMICAL", "SCHEDULE_4"),
            ("SUB-TRA", "Tramadol Hydrochloride", "Tramadol Hydrochloride", "CHEMICAL", "SCHEDULE_4"),
            ("SUB-INS", "Insulin Human", "Insulin Human", "BIOLOGICAL", "NONE"),
        ]
        substances = {}
        for code, c_name, d_name, s_type, ctrl in substances_data:
            sub, _ = ActiveSubstance.objects.get_or_create(
                code=code,
                defaults={
                    "is_global": True,
                    "canonical_name": c_name,
                    "display_name": d_name,
                    "search_name": c_name.lower(),
                    "substance_type": s_type,
                    "controlled_classification": ctrl,
                    "status": "ACTIVE",
                },
            )
            substances[code] = sub

        # 4. Manufacturers (10)
        mfg_data = [
            ("MFG-GSK", "GlaxoSmithKline LLC", "GSK", "United Kingdom"),
            ("MFG-PFI", "Pfizer Inc", "Pfizer", "United States"),
            ("MFG-NOV", "Novartis AG", "Novartis", "Switzerland"),
            ("MFG-AZ", "AstraZeneca PLC", "AstraZeneca", "United Kingdom"),
            ("MFG-SAN", "Sanofi SA", "Sanofi", "France"),
            ("MFG-BAY", "Bayer AG", "Bayer", "Germany"),
            ("MFG-TEV", "Teva Pharmaceutical Industries", "Teva", "Israel"),
            ("MFG-SUN", "Sun Pharmaceutical Industries", "Sun Pharma", "India"),
            ("MFG-CIP", "Cipla Ltd", "Cipla", "India"),
            ("MFG-DAW", "Dawa Limited", "Dawa Kenya", "Kenya"),
        ]
        manufacturers = {}
        for code, legal, trading, country in mfg_data:
            mfg, _ = Manufacturer.objects.get_or_create(
                code=code,
                defaults={"is_global": True, "legal_name": legal, "trading_name": trading, "country": country},
            )
            manufacturers[code] = mfg

        # 5. Clinical Medicinal Products (25 total, 5 multi-ingredient)
        clinical_data = [
            ("CMP-PAR-500-TAB", "Paracetamol 500 mg Tablet", "TAB", ["PO"], [("SUB-PAR", 500, "mg")]),
            ("CMP-PAR-120-SUSP", "Paracetamol 120 mg/5 mL Oral Suspension", "SUSP", ["PO"], [("SUB-PAR", 120, "mg")]),
            ("CMP-AMO-500-CAP", "Amoxicillin 500 mg Capsule", "CAP", ["PO"], [("SUB-AMO", 500, "mg")]),
            ("CMP-AMO-125-SUSP", "Amoxicillin 125 mg/5 mL Oral Suspension", "SUSP", ["PO"], [("SUB-AMO", 125, "mg")]),
            ("CMP-AUG-625-TAB", "Amoxicillin 500 mg + Clavulanate 125 mg Tablet", "TAB", ["PO"], [("SUB-AMO", 500, "mg"), ("SUB-CLA", 125, "mg")]),
            ("CMP-AUG-375-TAB", "Amoxicillin 250 mg + Clavulanate 125 mg Tablet", "TAB", ["PO"], [("SUB-AMO", 250, "mg"), ("SUB-CLA", 125, "mg")]),
            ("CMP-MET-500-TAB", "Metformin 500 mg Tablet", "TAB", ["PO"], [("SUB-MET", 500, "mg")]),
            ("CMP-MET-850-TAB", "Metformin 850 mg Tablet", "TAB", ["PO"], [("SUB-MET", 850, "mg")]),
            ("CMP-IBU-400-TAB", "Ibuprofen 400 mg Tablet", "TAB", ["PO"], [("SUB-IBU", 400, "mg")]),
            ("CMP-SAL-100-INH", "Salbutamol 100 mcg Inhaler", "INH", ["INH"], [("SUB-SAL", 100, "mcg")]),
            ("CMP-OME-20-CAP", "Omeprazole 20 mg Capsule", "CAP", ["PO"], [("SUB-OME", 20, "mg")]),
            ("CMP-CEF-1G-INJ", "Ceftriaxone 1 g Powder for Injection", "INJ", ["IV", "IM"], [("SUB-CEF", 1000, "mg")]),
            ("CMP-DIC-50-TAB", "Diclofenac Sodium 50 mg Tablet", "TAB", ["PO"], [("SUB-DIC", 50, "mg")]),
            ("CMP-DIC-1-GEL", "Diclofenac 1% Topical Gel", "CREAM", ["TOP"], [("SUB-DIC", 10, "mg")]),
            ("CMP-CIP-500-TAB", "Ciprofloxacin 500 mg Tablet", "TAB", ["PO"], [("SUB-CIP", 500, "mg")]),
            ("CMP-AZI-500-TAB", "Azithromycin 500 mg Tablet", "TAB", ["PO"], [("SUB-AZI", 500, "mg")]),
            ("CMP-LOS-50-TAB", "Losartan 50 mg Tablet", "TAB", ["PO"], [("SUB-LOS", 50, "mg")]),
            ("CMP-AML-5-TAB", "Amlodipine 5 mg Tablet", "TAB", ["PO"], [("SUB-AML", 5, "mg")]),
            ("CMP-AML-LOS-TAB", "Amlodipine 5 mg + Losartan 50 mg Tablet", "TAB", ["PO"], [("SUB-AML", 5, "mg"), ("SUB-LOS", 50, "mg")]),
            ("CMP-ATOR-20-TAB", "Atorvastatin 20 mg Tablet", "TAB", ["PO"], [("SUB-ATOR", 20, "mg")]),
            ("CMP-DEX-4-INJ", "Dexamethasone 4 mg/mL Injection", "INJ", ["IV", "IM"], [("SUB-DEX", 4, "mg")]),
            ("CMP-MOR-10-INJ", "Morphine 10 mg/mL Injection", "INJ", ["IV", "SC"], [("SUB-MOR", 10, "mg")]),
            ("CMP-COD-PAR-TAB", "Codeine 30 mg + Paracetamol 500 mg Tablet", "TAB", ["PO"], [("SUB-COD", 30, "mg"), ("SUB-PAR", 500, "mg")]),
            ("CMP-DIA-5-TAB", "Diazepam 5 mg Tablet", "TAB", ["PO"], [("SUB-DIA", 5, "mg")]),
            ("CMP-TRA-PAR-TAB", "Tramadol 37.5 mg + Paracetamol 325 mg Tablet", "TAB", ["PO"], [("SUB-TRA", 37.5, "mg"), ("SUB-PAR", 325, "mg")]),
        ]

        clinical_products = {}
        for code, c_name, df_code, r_codes, ing_list in clinical_data:
            cmp_obj, _ = ClinicalMedicinalProduct.objects.get_or_create(
                code=code,
                defaults={
                    "is_global": True,
                    "canonical_name": c_name,
                    "dose_form": dose_forms[df_code],
                    "status": "ACTIVE",
                },
            )
            cmp_obj.routes.set([routes[rc] for rc in r_codes])
            
            for idx, (sub_code, num_val, num_unit) in enumerate(ing_list, start=1):
                IngredientComposition.objects.get_or_create(
                    clinical_product=cmp_obj,
                    active_substance=substances[sub_code],
                    defaults={
                        "numerator_value": decimal.Decimal(str(num_val)),
                        "numerator_unit": num_unit,
                        "sequence": idx,
                    },
                )
            clinical_products[code] = cmp_obj

        # 6. Manufactured Products (30)
        mfg_prod_data = [
            ("MP-PAN-500", "Panadol 500mg Tablets", "CMP-PAR-500-TAB", "MFG-GSK"),
            ("MP-CAL-500", "Calpol 500mg Tablets", "CMP-PAR-500-TAB", "MFG-GSK"),
            ("MP-AUG-625", "Augmentin 625mg Tablets", "CMP-AUG-625-TAB", "MFG-GSK"),
            ("MP-AMO-500", "Amoxil 500mg Capsules", "CMP-AMO-500-CAP", "MFG-GSK"),
            ("MP-GLU-500", "Glucophage 500mg Tablets", "CMP-MET-500-TAB", "MFG-SAN"),
            ("MP-ADV-400", "Advil 400mg Tablets", "CMP-IBU-400-TAB", "MFG-PFI"),
            ("MP-VEN-100", "Ventolin 100mcg Inhaler", "CMP-SAL-100-INH", "MFG-GSK"),
            ("MP-LOSEC-20", "Losec 20mg Capsules", "CMP-OME-20-CAP", "MFG-AZ"),
            ("MP-ROCEPH-1G", "Rocephin 1g Injection", "CMP-CEF-1G-INJ", "MFG-NOV"),
            ("MP-VOLT-50", "Voltaren 50mg Tablets", "CMP-DIC-50-TAB", "MFG-NOV"),
            ("MP-CIPRO-500", "Ciproxin 500mg Tablets", "CMP-CIP-500-TAB", "MFG-BAY"),
            ("MP-ZITH-500", "Zithromax 500mg Tablets", "CMP-AZI-500-TAB", "MFG-PFI"),
            ("MP-COZAAR-50", "Cozaar 50mg Tablets", "CMP-LOS-50-TAB", "MFG-NOV"),
            ("MP-NORV-5", "Norvasc 5mg Tablets", "CMP-AML-5-TAB", "MFG-PFI"),
            ("MP-LIP-20", "Lipitor 20mg Tablets", "CMP-ATOR-20-TAB", "MFG-PFI"),
            ("MP-DAWA-PAR", "Dawa Paracetamol 500mg", "CMP-PAR-500-TAB", "MFG-DAW"),
            ("MP-DAWA-AMO", "Dawa Amoxicillin 500mg", "CMP-AMO-500-CAP", "MFG-DAW"),
            ("MP-CIPLA-MET", "Cipla Metformin 500mg", "CMP-MET-500-TAB", "MFG-CIP"),
            ("MP-SUN-IBU", "Sun Ibuprofen 400mg", "CMP-IBU-400-TAB", "MFG-SUN"),
            ("MP-TEVA-OME", "Teva Omeprazole 20mg", "CMP-OME-20-CAP", "MFG-TEV"),
            ("MP-DAWA-SUSP", "Dawa Paracetamol Suspension", "CMP-PAR-120-SUSP", "MFG-DAW"),
            ("MP-AUG-375", "Augmentin 375mg Tablets", "CMP-AUG-375-TAB", "MFG-GSK"),
            ("MP-GLU-850", "Glucophage 850mg Tablets", "CMP-MET-850-TAB", "MFG-SAN"),
            ("MP-VOLT-GEL", "Voltaren Emulgel 1%", "CMP-DIC-1-GEL", "MFG-NOV"),
            ("MP-DAWA-AZI", "Dawa Azithromycin 500mg", "CMP-AZI-500-TAB", "MFG-DAW"),
            ("MP-EXCED-TAB", "Co-Codamol 30/500 Tablets", "CMP-COD-PAR-TAB", "MFG-GSK"),
            ("MP-VALIUM-5", "Valium 5mg Tablets", "CMP-DIA-5-TAB", "MFG-NOV"),
            ("MP-ULTRAM-PAR", "Tramacet 37.5/325 Tablets", "CMP-TRA-PAR-TAB", "MFG-SAN"),
            ("MP-EXFORGE-AML", "Exforge 5/50 Tablets", "CMP-AML-LOS-TAB", "MFG-NOV"),
            ("MP-DEXA-INJ", "Dexamethasone 4mg Injection", "CMP-DEX-4-INJ", "MFG-CIP"),
        ]

        mfg_products = {}
        for code, brand, cmp_code, mfg_code in mfg_prod_data:
            mp, _ = ManufacturedMedicinalProduct.objects.get_or_create(
                code=code,
                defaults={
                    "is_global": True,
                    "brand_name": brand,
                    "clinical_product": clinical_products[cmp_code],
                    "manufacturer": manufacturers[mfg_code],
                    "status": "ACTIVE",
                },
            )
            mfg_products[code] = mp

        # 7. Package Definitions
        pkg_box_100, _ = PackageDefinition.objects.get_or_create(
            code="PKG-BOX-100",
            defaults={"description": "Box of 100 Tablets", "unit_of_measure": "tab", "pack_level": "OUTER"},
        )
        pkg_box_30, _ = PackageDefinition.objects.get_or_create(
            code="PKG-BOX-30",
            defaults={"description": "Box of 30 Capsules", "unit_of_measure": "cap", "pack_level": "OUTER"},
        )
        pkg_bottle_100ml, _ = PackageDefinition.objects.get_or_create(
            code="PKG-BOT-100ML",
            defaults={"description": "Bottle of 100 mL", "unit_of_measure": "mL", "pack_level": "BASE"},
        )

        # 8. Commercial SKUs (40) for Tenant
        tenant, _ = Tenant.objects.get_or_create(slug="default", defaults={"name": "Default Tenant"})
        
        skus_data = [
            ("SKU-PAN-100", "Panadol 500mg 100s Box", "MP-PAN-500", pkg_box_100, "600123456701"),
            ("SKU-CAL-100", "Calpol 500mg 100s Box", "MP-CAL-500", pkg_box_100, "600123456702"),
            ("SKU-AUG-14", "Augmentin 625mg 14s Pack", "MP-AUG-625", pkg_box_30, "600123456703"),
            ("SKU-AMO-100", "Amoxil 500mg 100s Box", "MP-AMO-500", pkg_box_100, "600123456704"),
            ("SKU-GLU-100", "Glucophage 500mg 100s Box", "MP-GLU-500", pkg_box_100, "600123456705"),
            ("SKU-ADV-100", "Advil 400mg 100s Box", "MP-ADV-400", pkg_box_100, "600123456706"),
            ("SKU-VEN-200", "Ventolin 100mcg Inhaler 200D", "MP-VEN-100", pkg_bottle_100ml, "600123456707"),
            ("SKU-LOSEC-28", "Losec 20mg 28s Pack", "MP-LOSEC-20", pkg_box_30, "600123456708"),
            ("SKU-ROCEPH-1", "Rocephin 1g 1 Vial", "MP-ROCEPH-1G", pkg_bottle_100ml, "600123456709"),
            ("SKU-VOLT-100", "Voltaren 50mg 100s Box", "MP-VOLT-50", pkg_box_100, "600123456710"),
        ]

        # Generate additional SKUs up to 40
        for i in range(11, 41):
            mp_key = list(mfg_products.keys())[i % len(mfg_products)]
            skus_data.append(
                (f"SKU-DEMO-{i:03d}", f"Demo Commercial SKU #{i}", mp_key, pkg_box_100, f"6001234567{i:02d}")
            )

        for sku_code, disp_name, mp_code, pkg_def, barcode in skus_data:
            sku, _ = CommercialSKU.objects.get_or_create(
                tenant=tenant,
                sku_code=sku_code,
                defaults={
                    "display_name": disp_name,
                    "manufactured_product": mfg_products[mp_code],
                    "package_definition": pkg_def,
                    "default_barcode": barcode,
                    "status": "ACTIVE",
                },
            )
            if barcode:
                ProductIdentifier.objects.get_or_create(
                    system="BARCODE",
                    value=barcode,
                    entity_type="SKU",
                    entity_id=sku.pk,
                    defaults={"is_primary": True},
                )

        # 9. Substitution Group & Policy
        sub_group, _ = SubstitutionGroup.objects.get_or_create(
            code="SUB-GRP-PAR-500",
            defaults={"name": "Paracetamol 500mg Oral Equivalents"},
        )
        sub_group.clinical_products.set([clinical_products["CMP-PAR-500-TAB"]])

        SubstitutionPolicy.objects.get_or_create(
            tenant=tenant,
            substitution_group=sub_group,
            defaults={"policy_type": "GENERIC_EQUIVALENT", "approval_required": True},
        )

        # 10. Branch Assortment
        from apps.organizations.models import Organization
        org, _ = Organization.objects.get_or_create(
            tenant=tenant,
            code="ORG-MAIN",
            defaults={"name": "Main Pharmacy Organization"},
        )
        location, _ = Location.objects.get_or_create(
            tenant=tenant,
            code="LOC-MAIN",
            defaults={"organization": org, "name": "Main Hospital Pharmacy Branch"},
        )
        for sku_obj in CommercialSKU.objects.filter(tenant=tenant)[:10]:
            BranchAssortment.objects.get_or_create(
                tenant=tenant,
                location=location,
                sku=sku_obj,
                defaults={"is_sellable": True, "is_dispensable": True, "is_stocked": True},
            )

        self.stdout.write(self.style.SUCCESS("✅ Enterprise medicine catalogue seeded successfully!"))
