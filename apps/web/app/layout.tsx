import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
