# 25: Portfolio, buyer view and alerts

**What to build:** The lender console's overview. A lender sees every invoice in their tenant in one table, narrows it, exports it, looks at one buyer across suppliers, and works a list of alerts.

**Blocked by:** 16

**Status:** resolved

- [x] Portfolio table columns: supplier, buyer, total, state, band, days late, claim value, exposure, loan-to-value, alerts
- [x] Filters by state, band and buyer; filters are reflected in the address so a view can be shared
- [x] CSV export of the filtered table, with figures identical to the screen
- [x] Each row opens the invoice detail page
- [x] Buyer view: all invoices to one buyer across suppliers in the tenant, the share accepted in IMS and the average days late, computed by the API
- [x] A lender can put a buyer on the watchlist and take them off; the mark shows in the portfolio
- [x] Alerts list: hard flags, loan-to-value breaches and bank-rate changes, each with Acknowledge and Assign
- [x] For invoices whose eligibility is `ineligible`, interest figures are hidden
- [x] Loading and empty states exist; the table is usable at phone width; the header stays in view while scrolling
- [x] No money arithmetic in the browser
- [x] A test through the API asserts the portfolio returns only the caller's tenant and honours each filter
