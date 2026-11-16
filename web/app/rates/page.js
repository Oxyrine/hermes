import { revalidatePath } from "next/cache";

// Bank-rate admin. Server component; the two operations users are distinct logins, so the
// API's two-person rule is what refuses self-approval. Development only (uses /dev/login).
export const dynamic = "force-dynamic";

const API = process.env.HERMES_API_URL || "http://localhost:8000";
const ENTERER = process.env.HERMES_DEV_EMAIL || "ops@lender-a.example";
const APPROVER = process.env.HERMES_RATE_APPROVER_EMAIL || "ops2@lender-a.example";

async function api(path, init) {
  const r = await fetch(`${API}${path}`, { cache: "no-store", ...init });
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
  return r.json();
}

async function headersFor(email) {
  const { token } = await api("/dev/login", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email }),
  });
  return { authorization: `Bearer ${token}`, "content-type": "application/json" };
}

async function enter(formData) {
  "use server";
  await api("/v1/admin/bank-rates", {
    method: "POST", headers: await headersFor(ENTERER),
    body: JSON.stringify(Object.fromEntries(["effective_from", "rate", "source_url"].map((k) => [k, formData.get(k)]))),
  });
  revalidatePath("/rates");
}

async function approve(formData) {
  "use server";
  await api(`/v1/admin/bank-rates/${encodeURIComponent(formData.get("day"))}/approve`, {
    method: "POST", headers: await headersFor(APPROVER),
  });
  revalidatePath("/rates");
}

export default async function Rates() {
  let rows;
  try {
    rows = await api("/v1/admin/bank-rates", { headers: await headersFor(ENTERER) });
  } catch (e) {
    return <main><h1>Bank rates</h1><p>API unavailable: {String(e.message)}</p></main>;
  }
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 760, margin: "2rem auto", padding: "0 1rem" }}>
      <h1>Bank rates</h1>
      <table>
        <thead><tr><th>Effective from</th><th>Rate (%)</th><th>Status</th><th>Source</th><th /></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.effective_from}>
              <td>{r.effective_from}</td><td>{r.rate}</td><td>{r.status}</td>
              <td><a href={r.source_url}>source</a></td>
              <td>{r.status === "pending" && (
                <form action={approve}><input type="hidden" name="day" value={r.effective_from} />
                  <button>Approve as second person</button></form>)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2>Enter a rate</h2>
      <form action={enter}>
        <label>Effective from <input type="date" name="effective_from" required /></label>{" "}
        <label>Rate % <input name="rate" inputMode="decimal" required size={6} /></label>{" "}
        <label>Source link <input type="url" name="source_url" required /></label>{" "}
        <button>Enter</button>
      </form>
    </main>
  );
}

export const metadata = { title: "Bank rates" };
