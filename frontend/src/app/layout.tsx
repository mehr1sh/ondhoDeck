import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { ConfigGate } from "@/components/ConfigGate";
import { ToastProvider } from "@/components/Toast";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "OndhoDeck", template: "%s · OndhoDeck" },
  description: "OndhoDeck — contract-aware liquidity analysis for financial advisors",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#2f6b4f",
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
