"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { usePathname } from "next/navigation";
import StaggeredMenu from "@/components/StaggeredMenu";
import { CONTACT } from "@/components/SiteFooter";

interface MobileStaggerNavProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const ITEMS = [
  { label: "Home", ariaLabel: "Go home", link: "/" },
  { label: "Documents", ariaLabel: "Manage documents", link: "/documents" },
  { label: "Datasets", ariaLabel: "Manage datasets", link: "/datasets" },
  { label: "History", ariaLabel: "Investigation history", link: "/investigations" },
  { label: "Settings", ariaLabel: "Open settings", link: "/settings" },
];

const SOCIALS = [
  { label: "Portfolio", link: CONTACT.portfolio },
  { label: "GitHub", link: CONTACT.github },
  { label: "LinkedIn", link: CONTACT.linkedin },
  { label: "Email", link: `mailto:${CONTACT.email}` },
];

/**
 * Mobile-only GSAP staggered menu, portaled under the pill navbar
 * (z-15: above page content, below the navbar so the hamburger + New
 * button stay visible and interactive). Desktop keeps the pill links.
 */
export default function MobileStaggerNav({ open, onOpenChange }: MobileStaggerNavProps) {
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onOpenChange]);

  if (!mounted || typeof document === "undefined") return null;

  return createPortal(
    <div className="md:hidden">
      <StaggeredMenu
        isFixed
        className="z-[15]"
        position="right"
        colors={["#e6b093", "#a3ceff", "#fffdf8"]}
        accentColor="#6366f1"
        items={ITEMS}
        socialItems={SOCIALS}
        displayItemNumbering
        displaySocials
        showHeader={false}
        open={open}
        onOpenChange={onOpenChange}
        activeLink={pathname}
        onItemClick={() => onOpenChange(false)}
      />
    </div>,
    document.body
  );
}
