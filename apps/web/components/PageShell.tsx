"use client";

import type { ReactNode } from "react";
import Navbar from "@/components/Navbar";
import { GradientBackground } from "@/components/ui/pipo";

export default function PageShell({
  children,
  wide = false,
}: {
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <main className="relative min-h-[100svh] overflow-hidden bg-[#faf9ef] text-[#24231f]">
      <GradientBackground className="fixed inset-0" />
      <Navbar />
      <div
        className={`relative z-10 mx-auto w-full px-4 pb-20 pt-8 sm:px-8 ${
          wide ? "max-w-5xl" : "max-w-4xl"
        }`}
      >
        {children}
      </div>
    </main>
  );
}
