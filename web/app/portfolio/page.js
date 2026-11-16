import { revalidatePath } from "next/cache";
import { Fig } from "../Fig";

// Lender portfolio, buyer watchlist and alerts. Development login only. Every figure is produced
// by the API; nothing is computed here. Filters live in the address (?state=&band=&buyer=).
export const dynamic = "force-dynamic";

const API = process.env.HERMES_API_URL || "http://localhost:8000";
const EMAIL = process.env.HERMES_DEV_EMAIL || "ops@lender-a.example";

async function call(path, init = {}) {
  const login = await fetch(`${API}/dev/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email: EMAIL }) });
  const { token } = await login.json();
  const r = await fetch(`${API}${path}`, { cache: "no-store", ...init, headers: { authorization: `Bearer ${token}`, "content-type": "application/json", ...init.headers } });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${r.status})`);
  return body;
}

async function watch(f) {
  "use server";
  await call(`/v1/buyers/${encodeURIComponent(f.get("buyer"))}/watchlist`, { method: f.get("on") === "1" ? "PUT" : "DELETE" }).catch(() => {});
  revalidatePath("/portfolio");
}

async function work(f) {
  "use server";
  const verb = f.get("verb") === "assign" ? "assign" : "acknowledge";
  await call(`/v1/alerts/${verb}`, { method: "POST", body: JSON.stringify({ key: f.get("key"), assignee: f.get("assignee") }) }).catch(() => {});
  revalidatePath("/portfolio");
}

const STATES = ["verified", "financeable", "advanced", "overdue", "settlement_offered", "odr_ready", "odr_filed", "awarded", "paid", "closed", "gst_blocked", "needs_review"];
const th = { position: "sticky", top: 0, background: "#f4f4f4", textAlign: "left", padding: "6px 8px", whiteSpace: "nowrap" };
const td = { padding: "6px 8px", borderTop: "1px solid #ddd", whiteSpace: "nowrap" };
const dash = (v, r) => (v === null || v === undefined ? "\u2013" : <Fig r={r}>{String(v)}</Fig>);

export default async function Portfolio({ searchParams }) {
  const q = await searchParams;
  const qs = new URLSearchParams(Object.entries(q).filter(([k, v]) => ["state", "band", "buyer"].includes(k) && v && typeof v === "string"));
  let rows, alerts;
  try {
    [rows, alerts] = await Promise.all([call(`/v1/portfolio?${qs}`), call("/v1/alerts")]);
  } catch (e) {
    return <main style={{ fontFamily: "system-ui", padding: "1rem" }}><h1>Portfolio</h1><p role="alert">Could not load: {e.message}</p></main>;
  }
  const buyers = [...new Map(rows.map((r) => [r.buyer_id, r.buyer]))];
  return (
    <main style={{ fontFamily: "system-ui", padding: "1rem" }}>
      <h1>Portfolio</h1>
      <form method="get" style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <label>State <select name="state" defaultValue={q.state || ""}><option value="">All</option>{STATES.map((s) => <option key={s}>{s}</option>)}</select></label>
        <label>Band <select name="band" defaultValue={q.band || ""}><option value="">All</option>{["A", "B", "C", "D"].map((b) => <option key={b}>{b}</option>)}</select></label>
        <label>Buyer <select name="buyer" defaultValue={q.buyer || ""}><option value="">All</option>{buyers.map(([id, n]) => <option key={id} value={id}>{n}</option>)}</select></label>
        <button type="submit">Filter</button>
        <a href={`/portfolio/export?${qs}`}>Export CSV</a>
      </form>

      <div style={{ overflow: "auto", maxHeight: "70vh" }}>
        <table style={{ borderCollapse: "collapse", minWidth: 900 }}>
          <thead><tr>{["Supplier", "Buyer", "Total", "State", "Band", "Days late", "Claim value", "Exposure", "LTV", "Alerts", ""].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td style={td} colSpan={11}>No invoices match.</td></tr>}
            {rows.map((r) => (
              <tr key={r.id}>
                <td style={td}><a href={`/invoice/${r.id}`}>{r.supplier}</a></td>
                <td style={td}>{r.watchlist && <span title="On watchlist">{"\u2605 "}</span>}{r.buyer}</td>
                <td style={td}>{dash(r.total, r.sources.total)}</td><td style={td}>{r.state}</td><td style={td}>{dash(r.band, r.sources.band)}</td>
                <td style={td}>{dash(r.days_late, r.sources.due)}</td><td style={td}>{dash(r.claim_value, r.sources.claim_value)}</td>
                <td style={td}>{dash(r.exposure, r.sources.exposure)}</td><td style={td}>{dash(r.ltv, r.sources.ltv)}</td>
                <td style={td}>{r.alerts.join(", ") || "\u2013"}</td>
                <td style={td}><form action={watch}><input type="hidden" name="buyer" value={r.buyer_id} /><input type="hidden" name="on" value={r.watchlist ? "0" : "1"} /><button type="submit">{r.watchlist ? "Unwatch" : "Watch"}</button></form></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Alerts</h2>
      {alerts.length === 0 && <p>No alerts.</p>}
      <ul style={{ paddingLeft: 0, listStyle: "none" }}>
        {alerts.map((a) => (
          <li key={a.key} style={{ border: "1px solid #ccc", borderRadius: 8, padding: 10, marginBottom: 8 }}>
            <strong>{a.message}</strong>{a.invoice_no && ` \u2013 ${a.invoice_no} (${a.buyer})`}
            {a.acknowledged_by && <div>Acknowledged by {a.acknowledged_by}</div>}
            {a.assigned_to && <div>Assigned to {a.assigned_to}</div>}
            <form action={work} style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
              <input type="hidden" name="key" value={a.key} />
              <button type="submit" name="verb" value="acknowledge">Acknowledge</button>
              <input name="assignee" type="email" placeholder="assignee email" aria-label="Assignee email" />
              <button type="submit" name="verb" value="assign">Assign</button>
            </form>
          </li>
        ))}
      </ul>
    </main>
  );
}

export const metadata = { title: "Portfolio" };
