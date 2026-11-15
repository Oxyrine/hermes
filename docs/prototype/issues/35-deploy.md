# 35: Deploy

**What to build:** The prototype is reachable on the internet for a demo: the API and the front end on Cloud Run and the ledger on Cloud SQL, in Mumbai, described in Terraform.

**Blocked by:** 34

**Status:** wontfix (deferred: run locally for now; revisit for cloud later)

Also blocked on something outside the tickets: a Google Cloud project with billing enabled, which the owner must create. Nothing here starts until it exists.

- [ ] Terraform describes only what the prototype needs: two Cloud Run services, one Cloud SQL for PostgreSQL 16 instance, one storage bucket and Secret Manager entries, all in asia-south1
- [ ] Secrets (database password, token signing key, Gemini key, webhook and link signing keys) live in Secret Manager and nowhere in the repository or images
- [ ] The deployed environment is not the development environment: the development login, clock and payment endpoints are off, or sit behind an explicit demo switch that is documented
- [ ] HTTPS only; security headers are set on the front end
- [ ] The synthetic-only guard is on; the deployed system holds synthetic data only
- [ ] Services scale to zero when idle
- [ ] The late-buyer scenario is walked through on the deployed address
- [ ] Teardown is one command and is documented
