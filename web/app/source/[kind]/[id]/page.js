// Source panel: where a figure came from. A document with its page and quote, or an engine run
// with its engine, rule version, inputs and reasons (and a recompute from those stored inputs),
// or the IMS event, payment or record behind an evidence signal. A page, so links work by keyboard
// and at phone width. Nothing is computed here.
export const dynamic = "force-dynamic";

const API = process.env.HERMES_API_URL || "http://localhost:8000";

async function call(path, init = {}) {
  const login = await fetch(`${API}/dev/login`, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ email: process.env.HERMES_DEV_EMAIL || "ops@lender-a.example" }) });
  const { token } = await login.json();
  const r = await fetch(`${API}${path}`, { cache: "no-store", ...init, headers: { authorization: `Bearer ${token}` } });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${r.status})`);
  return body;
}

const pre = { whiteSpace: "pre-wrap", overflowWrap: "anywhere", background: "#f4f4f4", padding: 8 };
const Json = ({ v }) => <pre style={pre}>{JSON.stringify(v, null, 2)}</pre>;

export default async function Source({ params, searchParams }) {
  const { kind, id } = await params;
  const q = await searchParams;
  let s, re;
  try {
    s = await call(`/v1/sources/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`);
    if (kind === "engine_run" && q.recompute) re = await call(`/v1/engine-runs/${encodeURIComponent(id)}/recompute`, { method: "POST" });
  } catch (e) {
    return <main style={{ fontFamily: "system-ui", padding: "1rem" }}><h1>Source</h1><p role="alert">Could not open this source: {e.message}</p></main>;
  }
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 760, margin: "2rem auto", padding: "0 1rem" }}>
      <nav><a href="/">Invoice</a> &middot; <a href="/portfolio">Portfolio</a></nav>
      <h1>Source: {kind.replace("_", " ")}</h1>
      {kind === "engine_run" && (<>
        <p><strong>{s.engine}</strong> engine, rule version {s.rule_version}
          {s.provisional && <> &middot; <strong style={{ color: "#9a6700" }}>provisional</strong>: a rule behind this result awaits legal review</>}</p>
        <p>Input hash <code style={{ overflowWrap: "anywhere" }}>{s.input_hash}</code></p>
        <h2>Inputs</h2><Json v={s.inputs} />
        <h2>Result</h2><Json v={s.result} />
        <h2>Reasons</h2>
        <ul>{(s.reasons || []).map((r, i) => <li key={i}>{r}</li>)}</ul>
        <h2>Recompute</h2>
        {re ? (
          <p role="status">{re.matches ? "Recomputed from the stored inputs: the output matches."
            : `Recomputed from the stored inputs: the output differs (${re.differs_in.join(", ")}). Stored rule ${re.stored_rule_version}, now ${re.current_rule_version}.`}</p>
        ) : (
          <form method="get"><button name="recompute" value="1">Recompute from stored inputs</button></form>
        )}
      </>)}
      {kind === "document" && (<>
        <p>{s.doc_type}{s.filename ? ` (${s.filename})` : ""}{s.extraction_model ? ` read by ${s.extraction_model}` : ""}</p>
        {s.fields.length === 0 && <p>No page or quote was recorded for this document.</p>}
        {s.fields.map((f) => (
          <figure key={f.field} style={{ margin: "0 0 12px" }}>
            <figcaption><strong>{f.field}</strong>: {String(f.value)} &middot; page {f.page}</figcaption>
            <blockquote style={{ margin: "4px 0" }}>{f.quote}</blockquote>
            {s.content_url && <a href={`/document/${s.id}#page=${f.page}`}>Open the document at page {f.page}</a>}
          </figure>
        ))}
        {s.content_url ? <p><a href={`/document/${s.id}`}>Open the document</a></p> : <p>The document file is not stored.</p>}
      </>)}
      {!["engine_run", "document"].includes(kind) && <Json v={s} />}
    </main>
  );
}
