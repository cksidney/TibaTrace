# Legacy Mercato Medicine Crosswalk Architecture

## Overview

Data migration from legacy Mercato uses DawaTrace's immutable `LegacyIdentifierCrosswalk` model (`apps.crosswalks`).

## Crosswalk System Identifiers
* `MERCATO_LEGACY_PRODUCT_ID`
* `MERCATO_LEGACY_ITEM_ID`
* `MERCATO_LEGACY_BARCODE`
* `MERCATO_LEGACY_MEDICINE_ID`

No live foreign keys or database links to Mercato exist.
