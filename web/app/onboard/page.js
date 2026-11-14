import Form from "./Form";

// Onboarding, consent and upload forms. Development only (uses /dev/login): onboarding is done as
// lender ops, consent and upload as the supplier user.
export const dynamic = "force-dynamic";

const API = process.env.HERMES_API_URL || "http://localhost:8000";
const LENDER = process.env.HERMES_DEV_EMAIL || "ops@lender-a.example";
const SUPPLIER = process.env.HERMES_SUPPLIER_EMAIL || "supplier@sundaram.example";

async function send(email, path, init = {}) {
  try {
    const login = await fetch(`${API}/dev/login`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email }),
    });
    const { token } = await login.json();
    const r = await fetch(`${API}${path}`, {
      method: "POST", cache: "no-store", ...init, headers: { authorization: `Bearer ${token}`, ...init.headers },
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) return { ok: false, message: typeof body.detail === "string" ? body.detail : `Request failed (${r.status})` };
    return { ok: true, body };
  } catch {
    return { ok: false, message: "The API is unavailable. Try again shortly." };
  }
}

const json = { "content-type": "application/json" };
const fields = (f, keys) => Object.fromEntries(keys.map((k) => [k, f.get(k)]));

async function onboard(_, f) {
  "use server";
  const classifications = { [f.get("fy")]: f.get("class") };
  const r = await send(LENDER, "/v1/suppliers", {
    headers: json,
    body: JSON.stringify({ ...fields(f, ["gstin", "legal_name", "udyam_urn", "udyam_reg_date", "enterprise_type"]), classifications }),
  });
  return r.ok ? { ok: true, message: `Onboarded. Supplier id: ${r.body.id}` } : r;
}

async function consent(_, f) {
  "use server";
  const r = await send(SUPPLIER, `/v1/suppliers/${encodeURIComponent(f.get("supplier_id"))}/consents`, {
    headers: json, body: JSON.stringify(fields(f, ["source", "purpose", "expires_at"])),
  });
  return r.ok ? { ok: true, message: `Consent recorded for ${r.body.source}, ${r.body.purpose}.` } : r;
}

async function upload(_, f) {
  "use server";
  const file = f.get("file");
  if (!file || !file.size) return { ok: false, message: "Choose a file to upload." };
  const q = new URLSearchParams({ filename: file.name, doc_type: f.get("doc_type") });
  if (f.get("invoice_id")) q.set("invoice_id", f.get("invoice_id"));
  const r = await send(SUPPLIER, `/v1/documents?${q}`, {
    headers: { "content-type": file.type }, body: Buffer.from(await file.arrayBuffer()),
  });
  return r.ok ? { ok: true, message: `Uploaded. SHA-256 ${r.body.sha256}` } : r;
}

const Opt = ({ list }) => list.map((v) => <option key={v}>{v}</option>);

export default function Onboard() {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 560, margin: "2rem auto", padding: "0 1rem" }}>
      <h1>Onboard a supplier</h1>
      <Form action={onboard} label="Onboard">
        <label>GSTIN <input name="gstin" required maxLength={15} /></label>
        <label>Legal name <input name="legal_name" required /></label>
        <label>Udyam number <input name="udyam_urn" required placeholder="UDYAM-MH-26-0001234" /></label>
        <label>Udyam registration date <input type="date" name="udyam_reg_date" required /></label>
        <label>Enterprise type <select name="enterprise_type"><Opt list={["manufacturing", "services", "trading"]} /></select></label>
        <label>Financial year <input name="fy" required placeholder="2026-27" /></label>
        <label>Class <select name="class"><Opt list={["micro", "small", "medium"]} /></select></label>
      </Form>

      <h1>Record consent</h1>
      <Form action={consent} label="Record consent">
        <label>Supplier id <input name="supplier_id" required /></label>
        <label>Data source <select name="source"><Opt list={["ims_supplier_view", "gstr1", "einvoice", "bank_statement", "email"]} /></select></label>
        <label>Purpose <select name="purpose"><Opt list={["underwriting", "servicing", "dispute_resolution"]} /></select></label>
        <label>Expires <input type="date" name="expires_at" required /></label>
      </Form>

      <h1>Upload a document</h1>
      <Form action={upload} label="Upload">
        <label>File (PDF, PNG, JPEG or WebP, up to 5 MB) <input type="file" name="file" accept="application/pdf,image/png,image/jpeg,image/webp" required /></label>
        <label>Document type <select name="doc_type"><Opt list={["certificate", "contract", "invoice", "po", "grn", "challan", "email", "debit_note", "bank_stmt"]} /></select></label>
        <label>Invoice id (leave empty for a certificate or contract of the supplier) <input name="invoice_id" /></label>
      </Form>
    </main>
  );
}
