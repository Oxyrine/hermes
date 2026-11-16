"use client";
export default function Error({ reset }) {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 480, margin: "4rem auto", padding: "1rem" }} role="alert">
      <h1>Something went wrong</h1>
      <p>The page could not be loaded. Check that the API is running, then try again.</p>
      <button onClick={reset}>Try again</button>
    </main>
  );
}
