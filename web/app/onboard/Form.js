"use client";
import { useActionState } from "react";

// One form shell for all three: pending, error and success states come from the server action's
// result ({ ok, message }); the API's own message is shown as it is.
export default function Form({ action, children, label }) {
  const [state, run, pending] = useActionState(action, null);
  return (
    <form action={run} aria-busy={pending} style={{ display: "grid", gap: ".5rem", marginBottom: "2rem" }}>
      {children}
      <button disabled={pending}>{pending ? "Working…" : label}</button>
      {state && <p role={state.ok ? "status" : "alert"} style={{ color: state.ok ? "green" : "crimson" }}>{state.message}</p>}
    </form>
  );
}
