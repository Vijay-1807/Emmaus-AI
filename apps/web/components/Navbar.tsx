"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import { apiFetch, ensureAnonymousSession } from "@/lib/api";
import type { Workspace } from "@/lib/types";
import { cn } from "@/lib/utils";
import MobileStaggerNav from "@/components/MobileStaggerNav";

const NAV_ITEMS = [
  { href: "/", label: "Home" },
  { href: "/documents", label: "Documents" },
  { href: "/datasets", label: "Datasets" },
  { href: "/investigations", label: "History" },
  { href: "/settings", label: "Settings" },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  async function handleNew() {
    if (creating) return;
    setCreating(true);
    try {
      await ensureAnonymousSession();
      const ws = await apiFetch<Workspace>("/api/workspaces", {
        method: "POST",
        body: JSON.stringify({ name: "New investigation" }),
      });
      localStorage.setItem("vedax_workspace_id", ws.id);
      window.dispatchEvent(new CustomEvent("vedax:workspaces-changed"));
      if (pathname !== "/") router.push("/");
    } catch (e) {
      console.error("createWorkspace failed:", e);
    } finally {
      setCreating(false);
    }
  }

  return (
    <nav className="relative z-20 mx-auto mt-4 flex w-[min(100%-32px,880px)] items-center justify-between rounded-full border border-white/30 bg-black/75 px-4 py-2 shadow-lg backdrop-blur-xl sm:px-5 sm:py-2.5">
      <Link href="/" className="text-base font-bold tracking-tight text-white sm:text-lg">
        Emmaus AI
      </Link>

      {/* Desktop links */}
      <div className="hidden items-center gap-0.5 md:flex">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "rounded-full px-3 py-1.5 text-xs font-medium transition backdrop-blur-sm",
              isActive(pathname, item.href)
                ? "bg-white/15 text-white shadow-sm"
                : "text-white/55 hover:text-white hover:bg-white/10"
            )}
          >
            {item.label}
          </Link>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={handleNew}
          disabled={creating}
          className="rounded-full bg-white/90 px-4 py-1.5 text-xs font-bold text-black transition hover:bg-white disabled:opacity-50"
        >
          {creating ? "…" : (<><span className="hidden sm:inline">New investigation</span><span className="sm:hidden">New</span></>)}
        </button>

        {/* Mobile burger — morphs to X in sync with the drawer */}
        <button
          className="flex h-7 w-7 items-center justify-center rounded-full text-white transition active:scale-90 md:hidden"
          onClick={() => setMobileOpen((v) => !v)}
          aria-label={mobileOpen ? "Close menu" : "Open menu"}
          aria-expanded={mobileOpen}
        >
          <motion.span
            animate={{ rotate: mobileOpen ? 180 : 0 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            className="grid place-items-center"
          >
            <AnimatePresence mode="wait" initial={false}>
              <motion.svg
                key={mobileOpen ? "x" : "burger"}
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                initial={{ opacity: 0, scale: 0.5, rotate: -45 }}
                animate={{ opacity: 1, scale: 1, rotate: 0 }}
                exit={{ opacity: 0, scale: 0.5, rotate: 45 }}
                transition={{ duration: 0.16 }}
              >
                {mobileOpen ? (
                  <path d="M18 6L6 18M6 6l12 12" />
                ) : (
                  <path d="M3 12h18M3 6h18M3 18h18" />
                )}
              </motion.svg>
            </AnimatePresence>
          </motion.span>
        </button>
      </div>

      {/* Mobile GSAP staggered menu (mobile only, docks under this pill) */}
      <MobileStaggerNav open={mobileOpen} onOpenChange={setMobileOpen} />
    </nav>
  );
}
