import os

files = [
    "backend/apps/procurement/tests/test_rbac_segregation.py",
    "backend/apps/procurement/tests/test_concurrency.py",
    "backend/apps/procurement/tests/test_purchase_orders.py",
    "backend/apps/procurement/tests/test_returns.py",
    "backend/apps/procurement/tests/test_quality.py",
    "backend/apps/procurement/tests/test_receiving.py",
    "backend/apps/procurement/tests/test_batches.py",
]

for f in files:
    with open(f, "r") as file:
        content = file.read()
    
    if "from apps.procurement.models import" in content and "SupplierQualification" not in content:
        content = content.replace("from apps.procurement.models import", "from apps.procurement.models import SupplierQualification,")
        
    replacement = """SupplierGovernanceService.approve_supplier(supplier=self.supplier, approver=self.user)
        SupplierQualification.objects.create(
            tenant=self.tenant, supplier=self.supplier, qualification_type=SupplierQualification.QualificationType.BUSINESS_REGISTRATION,
            verification_status=SupplierQualification.QualificationVerificationStatus.VERIFIED, expiry_date=datetime.date.today() + datetime.timedelta(days=365)
        )"""
    content = content.replace("SupplierGovernanceService.approve_supplier(supplier=self.supplier, approver=self.user)", replacement)
    
    replacement2 = """SupplierGovernanceService.approve_supplier(supplier=supplier, approver=user)
    SupplierQualification.objects.create(
        tenant=tenant, supplier=supplier, qualification_type=SupplierQualification.QualificationType.BUSINESS_REGISTRATION,
        verification_status=SupplierQualification.QualificationVerificationStatus.VERIFIED, expiry_date=datetime.date.today() + datetime.timedelta(days=365)
    )"""
    content = content.replace("SupplierGovernanceService.approve_supplier(supplier=supplier, approver=user)", replacement2)

    replacement3 = """SupplierGovernanceService.approve_supplier(supplier=self.supplier, approver=self.approver_user)
        SupplierQualification.objects.create(
            tenant=self.tenant, supplier=self.supplier, qualification_type=SupplierQualification.QualificationType.BUSINESS_REGISTRATION,
            verification_status=SupplierQualification.QualificationVerificationStatus.VERIFIED, expiry_date=datetime.date.today() + datetime.timedelta(days=365)
        )"""
    content = content.replace("SupplierGovernanceService.approve_supplier(supplier=self.supplier, approver=self.approver_user)", replacement3)

    if "import datetime" not in content:
        content = "import datetime\n" + content

    with open(f, "w") as file:
        file.write(content)
