export const metadata = { title: "Page not found" };
export default function NotFound() {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 480, margin: "4rem auto", padding: "1rem" }}>
      <h1>Page not found</h1>
      <p>This page does not exist, or the link is no longer valid.</p>
      <p><a href="/">Back to the invoice page</a></p>
    </main>
  );
}
