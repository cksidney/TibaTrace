# Commercial Pricing Model

## Overview
The Commercial Pricing Model defines tiering, customer price agreements, promotional price lists, and pricing resolution logic within `backend/apps/sales`.

## Pricing Entities
1. **PriceList**: Master price catalogue defined per tenant. Supports currency specification, effective date ranges (`effective_from`, `effective_to`), default flag (`is_default`), and status (`DRAFT`, `ACTIVE`, `EXPIRED`, `ARCHIVED`).
2. **PriceListEntry**: SKU-level price point within a PriceList. Enforces positive unit price and minimum quantity tiering (`minimum_quantity`).
3. **CustomerPriceAgreement**: Bilateral commercial price agreement overriding standard price lists for a specific customer and CommercialSKU. Specifies `agreed_price`, optional `discount_percentage`, effective date range, and approval audit fields.

## Price Resolution Precedence
`CommercialPricingService.resolve_price(*, tenant, customer, sku, quantity=1)` evaluates prices in strict deterministic order:

```
1. Customer Price Agreement (Active & Current Date)
   ├── Match tenant, customer, sku, is_active=True, effective date range
   └── Calculate agreed price & optional percentage discount
2. Customer Commercial Profile Price List
   ├── Customer's default price list from CommercialProfile
   └── Active PriceListEntry for target SKU
3. Default Tenant Price List
   ├── Tenant default PriceList (is_default=True)
   └── Active PriceListEntry for target SKU
4. Fallback Base Price
   └── Base price from SKU metadata or Decimal('0.00')
```

## Calculation Outputs
`resolve_price` returns a structured pricing payload:
```python
{
    'base_unit_price': Decimal,
    'agreed_unit_price': Decimal,
    'discount_amount': Decimal,
    'discount_percentage': Decimal,
    'price_list_ref': str or None
}
```
All monetary amounts are quantized to 2 decimal places to comply with accounting standards.
