import type { Metadata, Viewport } from "next";
import { Alfa_Slab_One, Atkinson_Hyperlegible_Next, Courier_Prime } from "next/font/google";
import "./globals.css";

const display = Alfa_Slab_One({ weight: "400", subsets: ["latin"], variable: "--f-display", display: "swap" });
const body = Atkinson_Hyperlegible_Next({ subsets: ["latin"], variable: "--f-body", display: "swap" });
const data = Courier_Prime({ weight: ["400", "700"], subsets: ["latin"], variable: "--f-data", display: "swap" });

export const metadata: Metadata = {
  title: "Jaminan — a PayPal hold instead of your passport",
  description: "Scooter-rental damage deposits as a PayPal authorization. The owner points; the shared baseline answers. What the shared baseline can't show, nobody can charge.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.svg" },
};
export const viewport: Viewport = { themeColor: "#F3EEE1", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${data.variable}`}>
      <body>{children}</body>
    </html>
  );
}
