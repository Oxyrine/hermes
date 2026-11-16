import { revalidatePath } from "next/cache";
import Form from "../onboard/Form";

// Supplier app: phone-first, English. Development only (uses /dev/login as the supplier user).
// Every sentence and figure is produced by the API (/v1/me/invoices, /v1/actions); nothing is computed here.
export const dynamic = "force-dynamic";

const API = process.env.HERMES_API_URL || "http://localhost:8000";
const EMAIL = process.env.HERMES_SUPPLIER_EMAIL || "supplier@sundaram.example";

async function call(path, init = {}) {
  const login = await fetch(`${API}/dev/login`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email: EMAIL }),
  });
  const { token } = await login.json();
  const r = await fetch(`${API}${path}`, { cache: "no-store", ...init, headers: { authorization: `Bearer ${token}`, ...init.headers } });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${r.status})`);
  return body;
}

async function upload(_, f) {
  "use server";
  const file = f.get("file");
  if (!file || !file.size) return { ok: false, message: "Choose a file to upload." };
  const q = new URLSearchParams({ filename: file.name, doc_type: f.get("doc_type"), invoice_id: f.get("invoice_id") });
  try {
    const b = await call(`/v1/documents?${q}`, { method: "POST", headers: { "content-type": file.type }, body: Buffer.from(await file.arrayBuffer()) });
    return { ok: true, message: `Uploaded. SHA-256 ${b.sha256}` };
  } catch (e) {
    return { ok: false, message: e.message };
  }
}

async function decide(f) {
  "use server";
  const verb = f.get("verb") === "approve" ? "approve" : "reject";
  await call(`/v1/actions/${encodeURIComponent(f.get("id"))}/${verb}`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ reason: verb === "reject" ? "declined by the supplier" : undefined }),
  }).catch(() => {});
  revalidatePath("/supplier");
}

const card = { border: "1px solid #ccc", borderRadius: 8, padding: 12, marginBottom: 12 };
const rupees = (n) => `\u20b9${n}`;

export default async function Supplier() {
  let invoices, actions;
  try {
    [invoices, actions] = await Promise.all([call("/v1/me/invoices"), call("/v1/actions?status=proposed")]);
  } catch (e) {
    return <main style={{ fontFamily: "system-ui", padding: "1rem" }}><h1>Your invoices</h1><p role="alert">Could not load: {e.message}</p></main>;
  }
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 480, margin: "0 auto", padding: "1rem", boxSizing: "border-box", overflowWrap: "anywhere" }}>
      <h1>Your invoices</h1>
      <p><a href="/onboard">Onboarding: GSTIN, Udyam certificate, consent for each data source</a></p>

      {invoices.length === 0 && <p>No invoices yet.</p>}
      {invoices.map((v) => (
        <section key={v.id} style={card}>
          <h2 style={{ margin: 0 }}>{v.invoice_no} &middot; {rupees(v.total)}</h2>
          <p>{v.status}</p>
          {v.cash && (
            <p><strong>Get cash: {rupees(v.cash.advance)} now.</strong> Cost: {v.cash.cost}.</p>
          )}
          <details>
            <summary>Why this?</summary>
            <p>{v.rule}. {v.advice}</p>
          </details>
          <details>
            <summary>Add a purchase order, goods receipt, challan or contract</summary>
            <Form action={upload} label="Upload">
              <input type="hidden" name="invoice_id" value={v.id} />
              <label>File (PDF, PNG, JPEG or WebP, up to 5 MB) <input type="file" name="file" accept="application/pdf,image/png,image/jpeg,image/webp" required style={{ maxWidth: "100%" }} /></label>
              <label>Document type <select name="doc_type">{["po", "grn", "challan", "contract"].map((t) => <option key={t}>{t}</option>)}</select></label>
            </Form>
          </details>
        </section>
      ))}

      <h1>Waiting for your approval</h1>
      {actions.length === 0 && <p>Nothing waiting.</p>}
      {actions.map((a) => (
        <form key={a.id} action={decide} style={card}>
          <input type="hidden" name="id" value={a.id} />
          {a.kind === "gstr1a_draft" ? (
            <>
              <p><strong>Fix it: correction draft.</strong> {a.draft.filed.what}. Hermes files nothing; give this to your accountant.</p>
              <p>Should have been: {a.draft.should_have_been.table} table{a.draft.should_have_been.buyer_gstin ? `, buyer GSTIN ${a.draft.should_have_been.buyer_gstin}` : ""}.</p>
              <details open><summary>Steps to amend</summary><ol>{a.draft.steps.map((t) => <li key={t}>{t}</li>)}</ol></details>
              <p style={{ fontSize: ".9em" }}>{a.draft.rule}. {a.draft.note}</p>
            </>
          ) : a.kind === "odr_pack" ? (
            <p><strong>Dispute pack.</strong> Approving releases it; a person files it, Hermes submits nothing.{" "}
              <a href={`/pack/${a.id}/pdf`}>Full document (PDF)</a></p>
          ) : (
            <>
              <p><strong>Settlement offer of {rupees(a.draft.offer)}</strong> to your buyer, sent in your name.</p>
              <details><summary>Full letter</summary><pre style={{ whiteSpace: "pre-wrap" }}>{a.draft.letter}</pre></details>
            </>
          )}
          <p style={{ fontSize: ".9em" }}>Talk to your accountant or a lawyer before you decide.</p>
          <button name="verb" value="approve" style={{ minHeight: 44 }}>{a.kind === "gstr1a_draft" ? "Got it" : "Approve"}</button>{" "}
          <button name="verb" value="reject" style={{ minHeight: 44 }}>{a.kind === "gstr1a_draft" ? "Dismiss" : "Reject"}</button>
        </form>
      ))}
    </main>
  );
}
