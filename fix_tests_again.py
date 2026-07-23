import os
import glob

files = glob.glob("backend/apps/procurement/tests/*.py")

for f in files:
    with open(f, "r") as file:
        content = file.read()
    
    # Ensure import
    if "SupplierQualification" in content and "from apps.procurement.models import SupplierQualification" not in content and "SupplierQualification," not in content:
        if "from apps.procurement.models import (" in content:
            content = content.replace("from apps.procurement.models import (", "from apps.procurement.models import (\n    SupplierQualification,")
        else:
            content = "from apps.procurement.models import SupplierQualification\n" + content
            
    # Add effective_date
    if "SupplierQualification.objects.create(" in content and "effective_date" not in content:
        content = content.replace("verification_status=SupplierQualification.QualificationVerificationStatus.VERIFIED,", "verification_status=SupplierQualification.QualificationVerificationStatus.VERIFIED, effective_date=datetime.date.today(),")
        
    with open(f, "w") as file:
        file.write(content)
