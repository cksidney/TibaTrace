import json
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum

from apps.sales.models import (
    DeliveryLine,
    DispatchLine,
    PackageLine,
    PickingTask,
    SalesOrderAllocation,
    SalesOrderLine,
    SalesReturnLine,
)
from apps.tenancy.models import Tenant


class Command(BaseCommand):
    help = "Check sales domain data integrity"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=str, help="Filter by tenant slug")

    def handle(self, *args, **options):
        tenant_slug = options["tenant"]
        if tenant_slug:
            try:
                tenant = Tenant.objects.get(slug=tenant_slug)
                tenant_q = Q(tenant=tenant)
            except Tenant.DoesNotExist:
                self.stderr.write(f"Tenant {tenant_slug} does not exist.")
                return
        else:
            tenant_q = Q()

        results = {"quantity_violations": [], "orphaned_records": [], "cross_tenant_references": []}

        # 1. Quantity constraints check on SalesOrderLine
        # approved <= requested, reserved <= approved, allocated <= reserved
        # picked <= allocated, packed <= picked, dispatched <= packed
        # delivered <= dispatched, returned <= delivered

        lines = SalesOrderLine.all_objects.filter(tenant_q)
        for line in lines:
            violations = []
            if line.approved_quantity > line.requested_quantity:
                violations.append(f"approved({line.approved_quantity}) > requested({line.requested_quantity})")
            if line.reserved_quantity > line.approved_quantity:
                violations.append(f"reserved({line.reserved_quantity}) > approved({line.approved_quantity})")
            if line.allocated_quantity > line.reserved_quantity:
                violations.append(f"allocated({line.allocated_quantity}) > reserved({line.reserved_quantity})")
            if line.picked_quantity > line.allocated_quantity:
                violations.append(f"picked({line.picked_quantity}) > allocated({line.allocated_quantity})")
            if line.packed_quantity > line.picked_quantity:
                violations.append(f"packed({line.packed_quantity}) > picked({line.picked_quantity})")
            if line.dispatched_quantity > line.packed_quantity:
                violations.append(f"dispatched({line.dispatched_quantity}) > packed({line.packed_quantity})")
            if line.delivered_quantity > line.dispatched_quantity:
                violations.append(f"delivered({line.delivered_quantity}) > dispatched({line.dispatched_quantity})")
            if line.returned_quantity > line.delivered_quantity:
                violations.append(f"returned({line.returned_quantity}) > delivered({line.delivered_quantity})")

            if violations:
                results["quantity_violations"].append(
                    {"model": "SalesOrderLine", "id": str(line.id), "violations": violations}
                )

        # 2. Check reconciliation across models

        # SalesOrderAllocation -> allocated_quantity
        allocations = (
            SalesOrderAllocation.all_objects.filter(tenant_q)
            .values("sales_order_line")
            .annotate(total_allocated=Sum("quantity"))
        )
        allocation_dict = {a["sales_order_line"]: a["total_allocated"] for a in allocations}

        # PickingTask -> picked_quantity
        picks = (
            PickingTask.all_objects.filter(tenant_q, status="PICKED")
            .values("sales_order_line")
            .annotate(total_picked=Sum("picked_quantity"))
        )
        pick_dict = {p["sales_order_line"]: p["total_picked"] for p in picks if p["sales_order_line"]}

        # PackageLine -> packed_quantity
        packs = (
            PackageLine.all_objects.filter(tenant_q).values("sales_order_line").annotate(total_packed=Sum("quantity"))
        )
        pack_dict = {p["sales_order_line"]: p["total_packed"] for p in packs}

        # DispatchLine -> dispatched_quantity
        dispatches = (
            DispatchLine.all_objects.filter(tenant_q)
            .values("sales_order_line")
            .annotate(total_dispatched=Sum("quantity"))
        )
        dispatch_dict = {d["sales_order_line"]: d["total_dispatched"] for d in dispatches}

        # DeliveryLine -> delivered_quantity
        deliveries = (
            DeliveryLine.all_objects.filter(tenant_q)
            .values("sales_order_line")
            .annotate(total_delivered=Sum("accepted_quantity"))
        )
        delivery_dict = {d["sales_order_line"]: d["total_delivered"] for d in deliveries}

        # SalesReturnLine -> returned_quantity
        returns = (
            SalesReturnLine.all_objects.filter(tenant_q)
            .values("sales_order_line")
            .annotate(total_returned=Sum("quantity"))
        )
        return_dict = {r["sales_order_line"]: r["total_returned"] for r in returns}

        for line in lines:
            line_id = line.id
            reconciliation_issues = []

            calc_alloc = allocation_dict.get(line_id, Decimal("0"))
            if calc_alloc != line.allocated_quantity:
                reconciliation_issues.append(
                    f"Allocation sum ({calc_alloc}) != line.allocated_quantity ({line.allocated_quantity})"
                )

            calc_pick = pick_dict.get(line_id, Decimal("0"))
            if calc_pick != line.picked_quantity:
                reconciliation_issues.append(f"Pick sum ({calc_pick}) != line.picked_quantity ({line.picked_quantity})")

            calc_pack = pack_dict.get(line_id, Decimal("0"))
            if calc_pack != line.packed_quantity:
                reconciliation_issues.append(f"Pack sum ({calc_pack}) != line.packed_quantity ({line.packed_quantity})")

            calc_dispatch = dispatch_dict.get(line_id, Decimal("0"))
            if calc_dispatch != line.dispatched_quantity:
                reconciliation_issues.append(
                    f"Dispatch sum ({calc_dispatch}) != line.dispatched_quantity ({line.dispatched_quantity})"
                )

            calc_deliver = delivery_dict.get(line_id, Decimal("0"))
            if calc_deliver != line.delivered_quantity:
                reconciliation_issues.append(
                    f"Delivery sum ({calc_deliver}) != line.delivered_quantity ({line.delivered_quantity})"
                )

            calc_return = return_dict.get(line_id, Decimal("0"))
            if calc_return != line.returned_quantity:
                reconciliation_issues.append(
                    f"Return sum ({calc_return}) != line.returned_quantity ({line.returned_quantity})"
                )

            if reconciliation_issues:
                results["quantity_violations"].append(
                    {
                        "model": "SalesOrderLine",
                        "id": str(line_id),
                        "violations": reconciliation_issues,
                        "type": "reconciliation",
                    }
                )

        # 3. Detect orphaned records
        for model in [SalesOrderAllocation, PickingTask, PackageLine, DispatchLine, DeliveryLine, SalesReturnLine]:
            orphans = model.all_objects.filter(tenant_q, sales_order_line__isnull=True)
            # Actually, PickingTask has allocation, not sales_order_line directly, but let's check its FKs
            for orphan in orphans:
                if hasattr(orphan, "sales_order_line"):
                    if orphan.sales_order_line is None:
                        results["orphaned_records"].append({"model": model.__name__, "id": str(orphan.id)})

        # 4. Detect cross-tenant references
        # Checking tenant_relation_fields for each model
        for model_cls in [
            SalesOrderLine,
            SalesOrderAllocation,
            PickingTask,
            PackageLine,
            DispatchLine,
            DeliveryLine,
            SalesReturnLine,
        ]:
            if not hasattr(model_cls, "tenant_relation_fields"):
                continue

            for obj in model_cls.all_objects.filter(tenant_q):
                for field in model_cls.tenant_relation_fields:
                    rel_obj = getattr(obj, field, None)
                    if rel_obj and hasattr(rel_obj, "tenant_id") and rel_obj.tenant_id != obj.tenant_id:
                        results["cross_tenant_references"].append(
                            {
                                "model": model_cls.__name__,
                                "id": str(obj.id),
                                "field": field,
                                "obj_tenant_id": str(obj.tenant_id),
                                "rel_tenant_id": str(rel_obj.tenant_id),
                            }
                        )

        self.stdout.write(self.style.SUCCESS("Check Complete."))
        self.stdout.write(json.dumps(results, indent=2))
