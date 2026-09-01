"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: "grid" },
  { href: "/workspace", label: "Investigate", icon: "search" },
  { href: "/documents", label: "Documents", icon: "file" },
  { href: "/datasets", label: "Datasets", icon: "table" },
  { href: "/investigations", label: "History", icon: "clock" },
  { href: "/evaluation", label: "Evaluation", icon: "bar-chart" },
  { href: "/observability", label: "Observability", icon: "activity" },
  { href: "/settings", label: "Settings", icon: "settings" },
];

const ICONS: Record<string, string> = {
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z",
  search: "M21 21l-5.2-5.2M17 10a7 7 0 11-14 0 7 7 0 0114 0z",
  file: "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8",
  table: "M3 3h18v18H3zM3 9h18M3 15h18M9 3v18M15 3v18",
  clock: "M12 22a10 10 0 110-20 10 10 0 010 20zM12 6v6l4 2",
  "bar-chart": "M12 20V10M18 20V4M6 20v-4",
  activity: "M22 12h-4l-3 9L9 3l-3 9H2",
  settings: "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z",
};

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 h-screen bg-surface border-r border-border flex flex-col shrink-0">
      <div className="px-4 py-4 border-b border-border">
        <Link href="/dashboard" className="text-base font-bold tracking-tight">
          VedaX AI
        </Link>
      </div>
      <nav className="flex-1 py-2 overflow-y-auto">
        {NAV.map((item) => {
          const active =
            pathname === item.href ||
            (item.href !== "/dashboard" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 px-4 py-2 mx-2 text-sm rounded-lg transition-colors",
                active
                  ? "bg-primary/10 text-primary"
                  : "text-text-muted hover:text-text hover:bg-surface-2"
              )}
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d={ICONS[item.icon] || ""} />
              </svg>
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="px-4 py-3 border-t border-border text-xs text-text-muted">
        v0.1.0
      </div>
    </aside>
  );
}
