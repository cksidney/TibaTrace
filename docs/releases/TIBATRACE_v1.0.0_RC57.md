# TibaTrace 1.0.0-rc57

Adds a governed recovery path for active legacy pharmacy tenants that were marked active without a pharmacy profile or first branch. A platform owner can record the missing legal and premises-licence details in Pharmacy Network, then provision the first organization and branch after a current PPB premises licence and named superintendent are present. Provisioning creates the standard empty inventory layout, including the main store; it does not seed stock, create a register, or open a cash shift.

Register creation, device activation, product and price setup, stock receipt, and the operator's actual opening cash count remain separate accountable steps. This server/HQ release does not change the installed Windows POS client or enable live Daraja/VSCU providers. No database migration is introduced.
