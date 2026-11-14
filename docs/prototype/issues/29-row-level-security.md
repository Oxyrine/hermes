# 29: Row-level security

**What to build:** Tenancy is enforced by the database as well as by the queries. Even a query that forgets its tenant filter returns nothing from another lender's book.

**Blocked by:** 13

**Status:** resolved

Cut-list position 5 of 5 (the last to be cut). If cut, tenant filtering in every query remains.

- [x] Row-level security is enabled on every tenant-scoped table, keyed on a per-request tenant setting
- [x] The API connects as a role that does not own the tables and cannot bypass the policies
- [x] The tenant setting is applied per request and cannot leak between requests on a shared connection
- [x] Buyers and bank rates remain global
- [x] A test logs in as a user of a second tenant and reads nothing belonging to the first, including by direct id
- [x] A test runs a deliberately unfiltered query as the application role and gets only the current tenant's rows
- [x] All existing scenarios still pass
