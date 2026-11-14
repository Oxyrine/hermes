// Dispute pack download (JSON or PDF), proxied so the invoice page can link to it. Development
// login only, like the page; the API serves the stored pack and nothing here computes.
const API = process.env.HERMES_API_URL || "http://localhost:8000";

export async function GET(_req, { params }) {
  const { id, fmt } = await params;
  const login = await fetch(`${API}/dev/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email: process.env.HERMES_DEV_EMAIL || "ops@lender-a.example" }),
  });
  const { token } = await login.json();
  const r = await fetch(`${API}/v1/actions/${encodeURIComponent(id)}/pack.${encodeURIComponent(fmt)}`, {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return new Response(r.body, { status: r.status, headers: {
    "content-type": r.headers.get("content-type") || "application/octet-stream",
    "content-disposition": `attachment; filename="dispute-pack.${fmt === "pdf" ? "pdf" : "json"}"`,
  } });
}
