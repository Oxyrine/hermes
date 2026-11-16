// Security headers on every page. HSTS is a deploy-time concern (ticket 35) and is not set here,
// because the prototype serves plain http on localhost.
const headers = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Content-Security-Policy", value: "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'" },
];
module.exports = { poweredByHeader: false, async headers() { return [{ source: "/:path*", headers }]; } };
