# Picking and Packing

## Overview
Picking and Packing govern warehouse operations for fulfilling allocated sales orders (`backend/apps/sales`).

## Picking Workflow (`PickingService`, `PickingWaveService`)
1. **Wave Creation**: `PickingWaveService.create_wave()` groups multiple sales orders by zone, branch, or priority. Status: `DRAFT` -> `RELEASED`.
2. **Task Generation**: `PickingService.create_picking_task()` generates discrete task lines (`PickingTask`) per allocation line, specifying source bin location, SKU, batch number, and requested quantity.
3. **Execution**: Tasks are assigned (`assign_task`), started (`start_task`), picked (`record_pick`), and verified (`verify_pick`). Short-picks automatically update task status to `SHORT_PICK`.

## Packing Workflow (`PackingService`)
1. **Packing Session**: `PackingService.create_session()` initializes a packing workbench session for a target sales order.
2. **Package Creation**: `PackingService.create_package()` creates physical containers (`Package`) with defined container types (`BOX`, `PALLET`, `COOLER_BOX`) and temperature zones (`AMBIENT`, `COLD_CHAIN_2_8C`, `FROZEN`).
3. **Item Packing**: `PackingService.pack_line()` adds verified picked items to `PackageLine`, validating that packed quantity does not exceed picked quantity.
4. **Sealing**: `PackingService.seal_package()` applies a tamper-evident seal number (`seal_number`), records verifier signature, and sets status to `SEALED`.
