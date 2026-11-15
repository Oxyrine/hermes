// A figure that opens its source: a plain link, so it works by keyboard and on a phone. `r` is the
// source reference the API attached to the figure ({kind, id, provisional?}); without one the
// figure is shown as plain text. Provisional marks rules still awaiting legal review.
export function Fig({ r, children }) {
  if (!r) return <>{children}</>;
  return (
    <>
      <a href={`/source/${r.kind}/${encodeURIComponent(r.id)}`} style={{ textDecoration: "underline dotted", padding: "2px 0" }}
         aria-label={`Source of ${typeof children === "string" ? children : "this figure"}`}>{children}</a>
      {r.provisional && <small style={{ marginLeft: 4, color: "#9a6700" }} title="A rule behind this result awaits legal review">(provisional)</small>}
    </>
  );
}
