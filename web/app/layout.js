import "./globals.css";

export const metadata = {
  title: { default: "Hermes", template: "%s | Hermes" },
  description: "Evidence, pricing and servicing layer between MSME suppliers and regulated lenders. Prototype on synthetic data.",
  robots: { index: false, follow: false }, // an application, not a marketing site
};
export const viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#main">Skip to content</a>
        <div id="main" tabIndex={-1}>{children}</div>
      </body>
    </html>
  );
}
