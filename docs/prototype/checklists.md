# Checklist audit (ticket 34)

Audited against the code on branch `t34-checklists`. Hermes is an application on synthetic data with no marketing site, no passwords and no cookies; applicability is judged on that basis. Status: **done** (implemented in this ticket), **fine** (already satisfied, confirmed in the code), **skipped** (deliberate, with the reason), **report** (needs real content or an owner decision, not invented here).

## Security (20)

| # | Item | Status | Evidence / reason |
|---|------|--------|-------------------|
| 1 | Hide API keys | fine | `GEMINI_API_KEY` is read from the environment or git-ignored `.env`; `.env.example` has it empty. The web app holds no key; it calls the API from server components. |
| 2 | Purge Git secrets | fine | `.env` is git-ignored and untracked; a history scan for Google key, private-key and `sk-` patterns across all branches found nothing. |
| 3 | Use public DB key | fine | N/A: the browser never reaches the database or holds a database key; only the API does. |
| 4 | Enable row-level security | fine | Ticket 29: RLS policies on every tenant table, API runs as non-bypass role `hermes_app` (`schema.sql`, `tests/test_row_level_security.py`). |
| 5 | Encrypt sensitive data | skipped | Synthetic data only (ADR 0001). Encryption at rest and in transit comes from Cloud SQL and HTTPS at deploy (ticket 35, deferred). |
| 6 | Enforce server-side auth | fine | Every `/v1` route verifies a signed HS256 token with tenant, role and expiry and checks the role; the browser does no authorisation. `/dev/*` exists only when `HERMES_ENV=development`; the default is production and refuses to start without `HERMES_TOKEN_SECRET`. |
| 7 | Lock record access | fine | Every query filters by tenant, RLS backs it, suppliers are further scoped to their own supplier id (`mine(who)`); documents are never public and each read is audited. |
| 8 | Block field tampering | fine | Writes go through the state machine and per-field validators; clients cannot set state, tenant, or computed figures. |
| 9 | Secure session cookies | fine | N/A: no cookies and no sessions; bearer tokens with an 8 hour expiry. |
| 10 | Hash passwords | skipped | N/A: no passwords exist. Real user authentication is a product decision outside the prototype (readme). |
| 11 | Rate limit login | skipped | N/A: the only login is the development login, which is off by default. Needed once real login exists. |
| 12 | Add bot protection | report | Needs a decision (a CAPTCHA service). Exposure today: one tokenised, signed, noindex buyer-statement link. |
| 13 | Parameterize queries | fine | psycopg `%s` placeholders throughout; the single f-string SQL interpolates a table name from a constant dict. |
| 14 | Validate all input | fine | Onboarding and invoice fields have type, length and choice validators; uploads checked for type, size and magic bytes; bad input returns 422. |
| 15 | Escape user content | fine | React escapes all output; no `dangerouslySetInnerHTML` anywhere. |
| 16 | Restrict file uploads | fine | PDF, PNG, JPEG, WebP only, 5 MB cap, content signature checked, stored as bytes with SHA-256, served as attachment. |
| 17 | Trim API responses | fine | Responses are purpose-built views; the webhook signing secret is returned once and stripped from the audit log; there are no password hashes to leak. |
| 18 | Add security headers | done | API: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` (tested). Web: the same plus a CSP (`frame-ancestors`, `object-src`, `form-action`, `base-uri`) and Permissions-Policy in `web/next.config.js`; `X-Powered-By` removed. A full script-src CSP was not added: Next injects inline scripts and a nonce setup is more than a prototype needs. |
| 19 | Force HTTPS | skipped | Deploy-only (ticket 35, deferred); HSTS is deliberately not sent over plain-http localhost. |
| 20 | Scan dependencies | done | See Dependencies below. Dependabot configured. |

## Launch (20)

| # | Item | Status | Evidence / reason |
|---|------|--------|-------------------|
| 1 | Custom 404 page | done | `web/app/not-found.js`; the buyer link already gives a plain "not valid" 404. |
| 2 | CTA above the fold | skipped | N/A: an application, not a landing page. |
| 3 | Meta title per page | done | Root template `%s \| Hermes`; each page exports its own title. |
| 4 | Meta description per page | done | Set once in the root layout; per-page descriptions are pointless for pages that are `noindex`. |
| 5 | Open Graph image | report | Needs a designed asset, and a noindex app is not shared as a link preview. |
| 6 | Favicon set | done | `web/app/icon.svg` (SVG, served by Next). A PNG/apple-touch set needs a designed mark; report. |
| 7 | robots.txt | done | `web/public/robots.txt` disallows everything, plus `noindex` in metadata; the prototype is not for search engines. |
| 8 | sitemap.xml | skipped | No public pages to list. |
| 9 | Alt text on every image | fine | There are no raster images; the one chart is an SVG with `role="img"` and an `aria-label`. |
| 10 | Mobile breakpoints | fine | Viewport meta set; pages are fluid single-column, the supplier app is phone-first (ticket 31). |
| 11 | Sticky mobile CTA | skipped | N/A: no conversion funnel. |
| 12 | Loading states | done | `web/app/loading.js` (status text) and `error.js` with retry; forms already set `aria-busy`. |
| 13 | Form error states | fine | Onboarding and upload forms show the API's message in an alert region; the supplier page shows load errors. |
| 14 | Thank you page | skipped | Forms confirm in place (success message with the file hash); a separate page adds nothing. |
| 15 | Privacy policy page | report | Needs real legal text and a named data controller. Not invented. Synthetic data only today. |
| 16 | Terms page | report | Same: needs real terms. |
| 17 | Cookie banner | skipped | No cookies and no tracking, so nothing to disclose. |
| 18 | Analytics installed | report | Needs a provider decision; none is wanted for a local prototype. If added later, prefer cookieless. |
| 19 | Real contact address | report | Needs the owner's real address; none invented. |
| 20 | Compressed images | fine | N/A: no images. |

## UX polish (20)

| # | Item | Status | Evidence / reason |
|---|------|--------|-------------------|
| 1 | Dark mode toggle | skipped | One deliberate light theme; a second theme is not worth building for the prototype. |
| 2 | Simple cookie banner | skipped | No cookies. |
| 3 | Site search | skipped | Not enough content; the portfolio page already filters by state, band and buyer. |
| 4 | Back-to-top button | skipped | Pages are short. |
| 5 | Mobile menus | skipped | No navigation menu to collapse; single column with plain links. |
| 6 | Loading animations | done | Loading status and `aria-busy`; an animated spinner adds nothing to server-rendered pages. |
| 7 | Hover states | done | Links and buttons dim on hover; visible `:focus-visible` outline (`web/app/globals.css`). |
| 8 | Scroll progress bar | skipped | Not a long-form content site. |
| 9 | Copy button | skipped | Nothing is meant to be copied; every figure links to its source instead (ticket 27). |
| 10 | Print stylesheet | done | Minimal: hides buttons and forms and link styling, so an invoice page prints as a report. |
| 11 | Sticky headers | skipped | There is no header or navigation bar to stick. |
| 12 | Skip-to-content link | done | In the root layout, visible on focus. |
| 13 | Password visibility toggle | skipped | N/A: no password fields. |
| 14 | UTM tracking | skipped | No campaign traffic and no analytics. |
| 15 | Form success state | fine | Upload and onboarding show a success message (`onboard/Form.js`). |
| 16 | Form error state | fine | Same component shows the API's error in an alert. |
| 17 | Confirmation modal | fine | The approval list is the explicit are-you-sure step: the approver reads the draft and the engine runs it cites, then approves; reject needs no confirmation because it changes nothing and records a reason. No destructive delete exists. |
| 18 | Last updated date | fine | Every figure block says "as of" its date and rule version. |
| 19 | Expandable FAQ | skipped | No FAQ content. |
| 20 | Floating contact | skipped | No public contact channel yet (see launch item 19). |

## Dependencies

- Python (`uv export` then `pip-audit`): no known vulnerabilities.
- npm, before: `next` 15.1.6 (1 critical, 2 high: Server Actions denial of service, plus vulnerable `postcss` and `sharp`). Fixed by upgrading `next` to 15.5.29 (the 15.x backport line, no breaking change).
- npm, remaining: `next` vendors `postcss` at a vulnerable version (high, source-map and `</style>` issues). `next@16` is a breaking upgrade, so instead `overrides` pins `postcss` to a patched release in `web/package.json`. `npm audit` now reports 0 vulnerabilities and `next build` passes. These postcss issues need attacker-controlled CSS at build time, which the prototype does not have.
- `.github/dependabot.yml` opens weekly update PRs for Python, npm and Actions.

## Items needing the owner

Bot protection, OG image and favicon artwork, privacy policy, terms, analytics provider, real contact address, real user authentication (password hashing, login rate limit).
