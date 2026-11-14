-- Hermes ledger schema: product spec section 4 plus the prototype additions (docs/prototype/spec.md).
-- Money NUMERIC(18,2) rupees, rates NUMERIC(9,6) percent, dates DATE in IST. Every tenant-scoped
-- table carries tenant_id; buyer and bank_rate are global. Plain SQL, no migration tool.

CREATE TABLE tenant (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('bank','nbfc')),
  max_ltv NUMERIC(5,4), lender_rate_nominal NUMERIC(9,6), created_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE app_user (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant, email TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK (role IN ('lender_ops','lender_approver','supplier','hermes_ops','agent')),
  supplier_id UUID,   -- set for supplier users: the only supplier whose invoices they may see
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE supplier (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant, gstin CHAR(15) NOT NULL UNIQUE,
  legal_name TEXT NOT NULL, udyam_urn TEXT, udyam_reg_date DATE,
  enterprise_type TEXT CHECK (enterprise_type IN ('manufacturing','services','trading')),
  onboarded_at TIMESTAMPTZ);

CREATE TABLE consent (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant, supplier_id UUID NOT NULL REFERENCES supplier,
  source TEXT NOT NULL, purpose TEXT NOT NULL, granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at TIMESTAMPTZ);

CREATE TABLE udyam_classification (supplier_id UUID NOT NULL REFERENCES supplier,
  tenant_id UUID NOT NULL REFERENCES tenant, fy TEXT NOT NULL,
  class TEXT NOT NULL CHECK (class IN ('micro','small','medium')), source_doc UUID,
  PRIMARY KEY (supplier_id, fy));

CREATE TABLE buyer (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), gstin CHAR(15) NOT NULL UNIQUE,
  legal_name TEXT NOT NULL, is_cpse BOOLEAN NOT NULL DEFAULT false,
  on_treds BOOLEAN NOT NULL DEFAULT false, watchlist BOOLEAN NOT NULL DEFAULT false);

CREATE TABLE contract (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant, supplier_id UUID NOT NULL REFERENCES supplier,
  buyer_id UUID NOT NULL REFERENCES buyer, signed_date DATE,
  written_payment_days INT,          -- NULL when no written term found
  terms_source JSONB,                -- {doc_id, page, quote}, confirmed by a human
  terms_confirmed_by UUID REFERENCES app_user, terms_confirmed_at TIMESTAMPTZ);

CREATE TABLE agent_run (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant, invoice_id UUID, runner TEXT, model TEXT,
  tokens_in INT, tokens_out INT, tool_calls INT, started_at TIMESTAMPTZ, duration_ms INT,
  status TEXT);

CREATE TABLE invoice (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant, supplier_id UUID NOT NULL REFERENCES supplier,
  buyer_id UUID NOT NULL REFERENCES buyer, contract_id UUID REFERENCES contract,
  invoice_no TEXT NOT NULL, invoice_date DATE, taxable_value NUMERIC(18,2),
  gst_amount NUMERIC(18,2), total NUMERIC(18,2) NOT NULL, irn TEXT, ewb_no TEXT,
  state TEXT NOT NULL, state_changed_at TIMESTAMPTZ,
  due_date DATE,                     -- stored due date, written from the deadline engine
  agent_session TEXT,
  case_number TEXT,                  -- dispute case number, entered by the person who filed
  UNIQUE (supplier_id, invoice_no));

CREATE TABLE document (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant,
  invoice_id UUID REFERENCES invoice,        -- nullable: unlinked or supplier-level documents
  supplier_id UUID REFERENCES supplier,
  doc_type TEXT NOT NULL CHECK (doc_type IN ('invoice','po','grn','challan','contract','email','debit_note','bank_stmt','award')),
  gcs_uri TEXT, sha256 CHAR(64), extracted JSONB, extraction_model TEXT,
  extraction_confidence NUMERIC(4,3));

CREATE TABLE ims_event (id BIGSERIAL PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenant,
  invoice_id UUID NOT NULL REFERENCES invoice,
  action TEXT NOT NULL CHECK (action IN ('accepted','rejected','pending','no_action')),
  action_at TIMESTAMPTZ, raw_ref TEXT, fetched_at TIMESTAMPTZ);   -- append-only

CREATE TABLE evidence_item (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant, invoice_id UUID NOT NULL REFERENCES invoice,
  signal TEXT NOT NULL, value JSONB, source_ref JSONB, detected_at TIMESTAMPTZ);

CREATE TABLE payment (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant, invoice_id UUID NOT NULL REFERENCES invoice,
  amount NUMERIC(18,2) NOT NULL, paid_on DATE NOT NULL, utr TEXT, source TEXT);

CREATE TABLE bank_rate (effective_from DATE PRIMARY KEY, rate NUMERIC(9,6) NOT NULL,
  source_url TEXT NOT NULL, entered_by UUID REFERENCES app_user, approved_by UUID REFERENCES app_user,
  CHECK (approved_by IS NULL OR approved_by <> entered_by));   -- two-person rule

CREATE TABLE engine_run (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant, invoice_id UUID REFERENCES invoice,
  engine TEXT NOT NULL, rule_version TEXT NOT NULL, inputs_hash CHAR(64) NOT NULL,
  inputs JSONB NOT NULL, outputs JSONB NOT NULL, run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  agent_run_id UUID REFERENCES agent_run);

CREATE TABLE advance (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant, invoice_id UUID NOT NULL REFERENCES invoice,
  principal NUMERIC(18,2) NOT NULL, nominal_rate NUMERIC(9,6) NOT NULL, disbursed_on DATE,
  status TEXT, repaid_on DATE);

CREATE TABLE collateral_snapshot (invoice_id UUID NOT NULL REFERENCES invoice,
  tenant_id UUID NOT NULL REFERENCES tenant, as_of DATE NOT NULL,
  claim_value NUMERIC(18,2), exposure NUMERIC(18,2), ltv NUMERIC(6,4), evidence_score INT,
  band CHAR(1), PRIMARY KEY (invoice_id, as_of));

CREATE TABLE action_request (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant, invoice_id UUID NOT NULL REFERENCES invoice,
  kind TEXT NOT NULL CHECK (kind IN ('settlement_offer','odr_pack','buyer_note','gstr1a_draft')),
  draft JSONB, status TEXT NOT NULL CHECK (status IN ('proposed','approved','rejected','sent','expired')),
  proposed_by TEXT, approved_by UUID REFERENCES app_user, approved_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ, reject_reason TEXT, edit_difference JSONB,
  lender_consent_required BOOLEAN NOT NULL DEFAULT false,
  lender_consent_by UUID REFERENCES app_user, lender_consent_at TIMESTAMPTZ);

CREATE TABLE audit_log (id BIGSERIAL PRIMARY KEY, tenant_id UUID REFERENCES tenant,
  at TIMESTAMPTZ NOT NULL DEFAULT now(), actor TEXT, action TEXT NOT NULL, object_type TEXT,
  object_id UUID, before JSONB, after JSONB);   -- append-only

CREATE TABLE raw_record (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant, source TEXT NOT NULL, payload JSONB NOT NULL,
  sha256 CHAR(64) NOT NULL, fetched_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE idempotency_key (tenant_id UUID NOT NULL REFERENCES tenant, key TEXT NOT NULL,
  request_hash CHAR(64) NOT NULL, response JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, key));

CREATE TABLE event_queue (id BIGSERIAL PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenant,
  invoice_id UUID, kind TEXT NOT NULL, payload JSONB, available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  claimed_at TIMESTAMPTZ, done_at TIMESTAMPTZ);

CREATE TABLE model_cache (cache_key TEXT PRIMARY KEY, task TEXT NOT NULL, model TEXT NOT NULL,
  prompt_version TEXT NOT NULL, doc_hash CHAR(64), response JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE webhook_subscription (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant, url TEXT NOT NULL, events TEXT[] NOT NULL,
  secret_ref TEXT, active BOOLEAN NOT NULL DEFAULT true);

CREATE TABLE webhook_delivery (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenant, subscription_id UUID NOT NULL REFERENCES webhook_subscription,
  event TEXT NOT NULL, payload JSONB, attempts INT NOT NULL DEFAULT 0, next_attempt_at TIMESTAMPTZ,
  delivered_at TIMESTAMPTZ, last_status INT);

CREATE TABLE clock (id BOOLEAN PRIMARY KEY DEFAULT true CHECK (id), today DATE NOT NULL);  -- development clock, at most one row

CREATE TABLE waterfall (invoice_id UUID PRIMARY KEY REFERENCES invoice,
  tenant_id UUID NOT NULL REFERENCES tenant, as_of DATE NOT NULL, receipts NUMERIC(18,2) NOT NULL,
  lender_exposure NUMERIC(18,2) NOT NULL, costs NUMERIC(18,2) NOT NULL, supplier NUMERIC(18,2) NOT NULL,
  rule_version TEXT NOT NULL, input_hash CHAR(64) NOT NULL);   -- the collateral engine's receipts split

-- The audit log and IMS events are append-only, enforced here and not in application code.
CREATE FUNCTION refuse_change() RETURNS trigger LANGUAGE plpgsql AS
  $$ BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END $$;
CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();
CREATE TRIGGER ims_event_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON ims_event
  FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();
