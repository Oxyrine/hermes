// Invoice page. Server component: every figure is formatted by the API; nothing is computed here.
export const dynamic = "force-dynamic";

const API = process.env.HERMES_API_URL || "http://localhost:8000";

async function api(path, init) {
  const r = await fetch(`${API}${path}`, { cache: "no-store", ...init });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

// Development only: the API serves /dev/login in the development environment alone.
async function load() {
  const { token } = await api("/dev/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email: process.env.HERMES_DEV_EMAIL || "ops@lender-a.example" }),
  });
  const headers = { authorization: `Bearer ${token}` };
  const [first] = await api("/v1/invoices", { headers });
  return api(`/v1/invoices/${first.id}`, { headers });
}

const Row = ({ k, v }) => (
  <tr>
    <th scope="row" style={{ textAlign: "left", paddingRight: 16 }}>{k}</th>
    <td>{v}</td>
  </tr>
);

export default async function Page() {
  let inv;
  try {
    inv = await load();
  } catch (e) {
    return <main><h1>Hermes</h1><p>API unavailable: {String(e.message)}</p></main>;
  }
  const { deadline: d, claim: c, evidence: ev, eligibility: el, collateral: col } = inv;
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 760, margin: "2rem auto", padding: "0 1rem" }}>
      <h1>Invoice {inv.invoice_no}</h1>
      <p>Total Rs {inv.total} &middot; state {inv.state} &middot; eligibility {el.status} ({el.rule_version})</p>

      <h2>Evidence: score {ev.score}, band {ev.band}</h2>
      <table>
        <thead><tr><th>Signal</th><th>Points</th><th>Source</th></tr></thead>
        <tbody>
          {ev.contributions.map((x, i) => (
            <tr key={i}>
              <td>{x.signal}</td><td>{x.points}</td>
              <td><code>{JSON.stringify(x.source)}</code>{x.note ? ` (${x.note})` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Deadline working ({d.rule_version})</h2>
      <table><tbody>
        <Row k="Acceptance" v={`${d.acceptance} (${d.basis})`} />
        <Row k="Payment due" v={d.due} />
        <Row k="Interest from" v={d.interest_from} />
      </tbody></table>
      <ul>{d.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>

      {c && (
        <>
          <h2>Claim as of {c.as_of} ({c.rule_version})</h2>
          <table><tbody>
            <Row k="Principal" v={`Rs ${c.principal}`} />
            <Row k="Statutory interest" v={`Rs ${c.interest}`} />
            <Row k="Claim value" v={`Rs ${c.claim_value}`} />
            <Row k="Exposure" v={`Rs ${col.exposure}`} />
            <Row k="Loan-to-value" v={col.ltv ?? "no advance"} />
          </tbody></table>
          <ul>{c.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </>
      )}
    </main>
  );
}
