// A source document, proxied so the source panel can open it (at a page, with #page=N). Development
// login only; the API checks the caller, scopes the read and audits it.
const API = process.env.HERMES_API_URL || "http://localhost:8000";

export async function GET(_req, { params }) {
  const { id } = await params;
  const login = await fetch(`${API}/dev/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email: process.env.HERMES_DEV_EMAIL || "ops@lender-a.example" }),
  });
  const { token } = await login.json();
  const r = await fetch(`${API}/v1/documents/${encodeURIComponent(id)}/content`, {
    headers: { authorization: `Bearer ${token}` }, cache: "no-store" });
  return new Response(r.body, { status: r.status, headers: {
    "content-type": r.headers.get("content-type") || "application/octet-stream",
    "content-disposition": 'inline; filename="document"', "x-content-type-options": "nosniff" } });
}
