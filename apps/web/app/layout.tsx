import type { Metadata } from "next";
import { Playfair_Display } from "next/font/google";
import "./globals.css";

const editorial = Playfair_Display({
  subsets: ["latin"],
  style: ["normal", "italic"],
  weight: ["400", "500", "600"],
  variable: "--font-playfair",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Emmaus AI",
  description: "Multimodal Agentic Knowledge & Analysis Platform",
  icons: {
    icon: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={editorial.variable}>
      <body>{children}</body>
    </html>
  );
}
