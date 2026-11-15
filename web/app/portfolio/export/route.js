// CSV export of the filtered portfolio, proxied from the API; the figures are the API's, unchanged.
const API = process.env.HERMES_API_URL || "http://localhost:8000";

export async function GET(req) {
  const login = await fetch(`${API}/dev/login`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ email: process.env.HERMES_DEV_EMAIL || "ops@lender-a.example" }),
  });
  const { token } = await login.json();
  const r = await fetch(`${API}/v1/portfolio.csv${new URL(req.url).search}`, { headers: { authorization: `Bearer ${token}` }, cache: "no-store" });
  return new Response(r.body, { status: r.status, headers: { "content-type": "text/csv", "content-disposition": 'attachment; filename="portfolio.csv"' } });
}
