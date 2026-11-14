import { revalidatePath } from "next/cache";

// Invoice page. Server component: every figure is formatted by the API; nothing is computed here.
export const dynamic = "force-dynamic";

const API = process.env.HERMES_API_URL || "http://localhost:8000";

async function api(path, init) {
  const r = await fetch(`${API}${path}`, { cache: "no-store", ...init });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

// Development only: the API serves /dev/login in the development environment alone.
async function headersFor(email) {
  const { token } = await api("/dev/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email }),
  });
  return { authorization: `Bearer ${token}` };
}

// Approve or reject as the named approver; the API records who and when.
async function decide(formData) {
  "use server";
  const verb = formData.get("verb") === "approve" ? "approve" : "reject";
  // the supplier approves offers and releases dispute packs
  const headers = await headersFor(process.env.HERMES_SUPPLIER_EMAIL || "supplier@sundaram.example");
  await api(`/v1/actions/${encodeURIComponent(formData.get("id"))}/${verb}`, {
    method: "POST",
    headers: { ...headers, "content-type": "application/json" },
    body: JSON.stringify({ reason: verb === "reject" ? "rejected on the approval list" : undefined }),
  });
  revalidatePath("/");
}

async function load() {
  const headers = await headersFor(process.env.HERMES_DEV_EMAIL || "ops@lender-a.example");
  const [first] = await api("/v1/invoices", { headers });
  const supplier = await headersFor(process.env.HERMES_SUPPLIER_EMAIL || "supplier@sundaram.example");
  const [inv, series, timeline, actions, filed] = await Promise.all([
    api(`/v1/invoices/${first.id}`, { headers }),
    api(`/v1/invoices/${first.id}/collateral-series`, { headers }),
    api(`/v1/invoices/${first.id}/timeline`, { headers }),
    api("/v1/actions?status=proposed", { headers: supplier }),
    api("/v1/actions?status=approved", { headers: supplier }),
  ]);
  const odr = (a) => a.kind === "odr_pack";
  return { ...inv, series, timeline, actions, released: filed.filter(odr) };
}

// Two lines (claim value, exposure) from API series. Number() only positions points on the
// canvas; every figure shown is the API's string.
function Chart({ series }) {
  if (series.length < 2) return <p>Chart appears once the clock has been ticked on two days.</p>;
  const W = 600, H = 200;
  const vals = series.flatMap((p) => [Number(p.claim_value), Number(p.exposure)]);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pts = (k) => series.map((p, i) =>
    `${(i / (series.length - 1)) * W},${H - ((Number(p[k]) - lo) / (hi - lo || 1)) * H}`).join(" ");
  const last = series[series.length - 1];
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Claim value and exposure over time">
        <polyline points={pts("claim_value")} fill="none" stroke="#1a7f37" strokeWidth="2" />
        <polyline points={pts("exposure")} fill="none" stroke="#b42318" strokeWidth="2" />
      </svg>
      <figcaption>
        <span style={{ color: "#1a7f37" }}>Claim value</span> Rs {last.claim_value} and{" "}
        <span style={{ color: "#b42318" }}>exposure</span> Rs {last.exposure} on {last.as_of};
        from {series[0].as_of}.
      </figcaption>
    </figure>
  );
}

const PackLinks = ({ id }) => (
  <>Download: <a href={`/pack/${id}/pdf`}>PDF</a> &middot; <a href={`/pack/${id}/json`}>JSON</a></>
);

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

      <h2>Claim value against exposure</h2>
      <Chart series={inv.series} />

      <h2>Approval list</h2>
      {inv.actions.length === 0 ? <p>Nothing awaiting approval.</p> : inv.actions.map((a) => (
        <form key={a.id} action={decide} style={{ border: "1px solid #ccc", padding: 12, marginBottom: 12 }}>
          <input type="hidden" name="id" value={a.id} />
          <input type="hidden" name="kind" value={a.kind} />
          {a.kind === "odr_pack" ? (
            <>
              <p><strong>Dispute pack</strong> &middot; the supplier approves its release; a person files it
                on the portal (Hermes submits nothing). <PackLinks id={a.id} /></p>
              <p>Relies on: {a.draft.cites.map((c) => `${c.engine} ${c.rule_version}`).join(", ")}</p>
            </>
          ) : (<>
          <p><strong>{a.kind}</strong> &middot; offer Rs {a.draft.offer} &middot; floor Rs {a.draft.floor}
            {a.draft.needs_lender_consent ? " (needs lender consent)" : ""}</p>
          <pre style={{ whiteSpace: "pre-wrap" }}>{a.draft.letter}</pre>
          <p>Relies on: {a.draft.cites.map((c) => `${c.engine} ${c.rule_version}`).join(", ")}</p>
          </>)}
          <button name="verb" value="approve">Approve</button>{" "}
          <button name="verb" value="reject">Reject</button>
        </form>
      ))}

      {inv.released.map((a) => (
        <p key={a.id}>Dispute pack released {a.approved_at}. <PackLinks id={a.id} /></p>
      ))}

      {inv.waterfall && (
        <>
          <h2>Waterfall as of {inv.waterfall.as_of} ({inv.waterfall.rule_version})</h2>
          <table><tbody>
            <Row k="Receipts" v={`Rs ${inv.waterfall.receipts}`} />
            <Row k="To lender (exposure)" v={`Rs ${inv.waterfall.lender_exposure}`} />
            <Row k="Agreed costs" v={`Rs ${inv.waterfall.costs}`} />
            <Row k="To supplier (incl. all statutory interest)" v={`Rs ${inv.waterfall.supplier}`} />
          </tbody></table>
        </>
      )}

      <h2>Timeline</h2>
      <ol>
        {inv.timeline.map((t, i) => (
          <li key={i}>
            {t.at} &middot; {t.kind === "state_change" ? `state ${t.from} to ${t.to}`
              : t.kind === "engine_run" ? `engine ${t.engine} (${t.rule_version})` : `event ${t.event}`}
          </li>
        ))}
      </ol>

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
