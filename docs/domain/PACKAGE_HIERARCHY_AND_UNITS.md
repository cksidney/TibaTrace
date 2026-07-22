# Package Hierarchy and Units of Measure

## Overview

DawaTrace models commercial packaging as a tree hierarchy using `PackageDefinition`.

## Pack Levels
* **`BASE`**: Individual unit (e.g., 1 tablet, 1 mL).
* **`INNER`**: Primary blister or strip (e.g., blister of 10 tablets).
* **`OUTER`**: Retail box or carton (e.g., box of 10 blisters / 100 tablets).
* **`CARTON`**: Wholesale shipper box.

## Units of Measure
Explicit flags distinguish dispensing, procurement, and sales packaging levels (`is_dispensing_unit`, `is_procurement_unit`, `is_sales_unit`).
