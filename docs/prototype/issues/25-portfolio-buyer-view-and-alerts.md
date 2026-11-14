# 25: Portfolio, buyer view and alerts

**What to build:** The lender console's overview. A lender sees every invoice in their tenant in one table, narrows it, exports it, looks at one buyer across suppliers, and works a list of alerts.

**Blocked by:** 16

**Status:** ready-for-agent

- [ ] Portfolio table columns: supplier, buyer, total, state, band, days late, claim value, exposure, loan-to-value, alerts
- [ ] Filters by state, band and buyer; filters are reflected in the address so a view can be shared
- [ ] CSV export of the filtered table, with figures identical to the screen
- [ ] Each row opens the invoice detail page
- [ ] Buyer view: all invoices to one buyer across suppliers in the tenant, the share accepted in IMS and the average days late, computed by the API
- [ ] A lender can put a buyer on the watchlist and take them off; the mark shows in the portfolio
- [ ] Alerts list: hard flags, loan-to-value breaches and bank-rate changes, each with Acknowledge and Assign
- [ ] For invoices whose eligibility is `ineligible`, interest figures are hidden
- [ ] Loading and empty states exist; the table is usable at phone width; the header stays in view while scrolling
- [ ] No money arithmetic in the browser
- [ ] A test through the API asserts the portfolio returns only the caller's tenant and honours each filter
