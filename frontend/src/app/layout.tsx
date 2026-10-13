import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { ConfigGate } from "@/components/ConfigGate";
import { ToastProvider } from "@/components/Toast";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "SlipSlopes", template: "%s · SlipSlopes" },
  description: "SlipSlopes — Contractual Liquidity Intelligence",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#1e293b",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <ToastProvider>
          <ConfigGate>{children}</ConfigGate>
        </ToastProvider>
      </body>
    </html>
  );
}
