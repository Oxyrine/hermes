import { revalidatePath } from "next/cache";

// Buyer statement. Read-only, on a signed link; every figure is formatted by the API.
export const dynamic = "force-dynamic";
export const metadata = { title: "Invoice statement", robots: { index: false, follow: false } };

const API = process.env.HERMES_API_URL || "http://localhost:8000";

async function respond(formData) {
  "use server";
  const token = formData.get("token");
  await fetch(`${API}/public/statement/${encodeURIComponent(token)}/respond`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ choice: formData.get("choice"), note: formData.get("note") }),
  });
  revalidatePath(`/buyer/${token}`);
}

const LABELS = { will_pay: "I will pay", dispute: "I disagree with this statement", contact_me: "Please contact me" };

export default async function Statement({ params }) {
  const { token } = await params;
  const r = await fetch(`${API}/public/statement/${encodeURIComponent(token)}`, { cache: "no-store" });
  if (!r.ok) return <main><p>This link is not valid.</p></main>;
  const s = await r.json();
  const e = s.delivery_evidence;
  return (
    <main>
      <h1>Statement for invoice {s.invoice.invoice_no}</h1>
      <p>From {s.invoice.supplier} to {s.invoice.buyer}, as of {s.as_of}.</p>
      <dl>
        <dt>Invoice date</dt><dd>{s.invoice.invoice_date}</dd>
        <dt>Invoice total</dt><dd>{s.invoice.total}</dd>
        <dt>Delivery recorded</dt><dd>{e.delivery_date} ({e.signals.join(", ") || "no further evidence"})</dd>
        <dt>Acceptance date</dt><dd>{s.acceptance_date}</dd>
        <dt>Due date</dt><dd>{s.due_date}</dd>
        <dt>Days late</dt><dd>{s.days_late}</dd>
        <dt>Interest to date</dt><dd>{s.interest_to_date}</dd>
        <dt>Amount with interest</dt><dd>{s.amount_with_interest}</dd>
      </dl>
      {s.notes.map((n) => <p key={n}>{n}</p>)}
      <form action={respond}>
        <input type="hidden" name="token" value={token} />
        <select name="choice">{s.choices.map((c) => <option key={c} value={c}>{LABELS[c]}</option>)}</select>
        <input name="note" placeholder="Optional note" maxLength={1000} />
        <button type="submit">Send reply</button>
      </form>
      <p>Hermes does not take payment. Pay the supplier or lender directly.</p>
    </main>
  );
}
