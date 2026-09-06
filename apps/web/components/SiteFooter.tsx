"use client";

import Link from "next/link";
import { motion } from "motion/react";
import { Github, Linkedin, Mail, Send } from "lucide-react";

export const CONTACT = {
  portfolio: "https://vijaybontha.vercel.app/",
  linkedin: "https://www.linkedin.com/in/bonthavijay",
  github: "https://github.com/Vijay-1807",
  email: "bonthavijay1807@gmail.com",
  // ── Coming later: device mockups + telegram bot ──
  // telegram: "https://t.me/<your-bot>",
  // phoneMockups: "/showcase/phones",
  // laptopMockups: "/showcase/laptops",
};

const LINK_GROUPS: { header: string; links: { label: string; href: string; external?: boolean }[] }[] = [
  {
    header: "Discover",
    links: [
      { label: "Documents", href: "/documents" },
      { label: "Datasets", href: "/datasets" },
      { label: "History", href: "/investigations" },
      { label: "Evaluation", href: "/settings?tab=evaluation" },
      { label: "Observability", href: "/settings?tab=observability" },
    ],
  },
  {
    header: "The Mission",
    links: [
      { label: "Portfolio", href: CONTACT.portfolio, external: true },
      { label: "GitHub", href: CONTACT.github, external: true },
      { label: "LinkedIn", href: CONTACT.linkedin, external: true },
      { label: "Join the Team", href: `mailto:${CONTACT.email}?subject=Joining%20Emmaus%20AI`, external: true },
    ],
  },
  {
    header: "Concierge",
    links: [
      { label: "Get in Touch", href: `mailto:${CONTACT.email}`, external: true },
      { label: "Settings", href: "/settings" },
      { label: "Report Concern", href: `mailto:${CONTACT.email}?subject=Emmaus%20AI%20concern`, external: true },
    ],
  },
];

const SOCIALS = [
  { label: "Email", href: `mailto:${CONTACT.email}`, Icon: Mail },
  { label: "LinkedIn", href: CONTACT.linkedin, Icon: Linkedin },
  { label: "GitHub", href: CONTACT.github, Icon: Github },
  // Telegram bot slot — uncomment when live:
  // { label: "Telegram", href: CONTACT.telegram, Icon: Send },
];

/** Liquid-glass footer (Lumina layout, Emmaus brand + your links, our Pipo bg). */
export default function SiteFooter() {
  return (
    <motion.footer
      initial={{ opacity: 0, y: 40 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 1, delay: 0.4, ease: "easeOut" }}
      className="liquid-glass-dark w-full rounded-2xl p-3 md:p-5 text-white/70 mt-10 md:mt-14"
    >
      {/* Top grid — compact 3-col strip on mobile, full layout on desktop */}
      <div className="grid grid-cols-3 gap-3 md:grid-cols-12 md:gap-8 mb-4 md:mb-5">
        <div className="col-span-3 md:col-span-5">
          <div className="flex items-center gap-2 text-white">
            <span className="font-display text-base md:text-lg font-medium tracking-tight">Emmaus AI</span>
          </div>
          <p className="hidden md:block mt-2 text-[13px] leading-relaxed max-w-sm">
            Drop in docs, data, images, or audio - get clear answers with
            citations. Built in the open.
          </p>
          {/* Showcase slots (phone / laptop mockups) mount here later */}
        </div>

        <div className="col-span-3 md:col-span-7 grid grid-cols-3 gap-3 md:gap-8">
          {LINK_GROUPS.map((group) => (
            <div key={group.header}>
              <h4 className="text-[11px] md:text-sm uppercase tracking-wider text-white font-medium mb-1.5 md:mb-2">
                {group.header}
              </h4>
              <ul className="text-[11px] md:text-xs space-y-1 md:space-y-1.5">
                {group.links.map((link) => (
                  <li key={link.label}>
                    {link.external ? (
                      <a
                        href={link.href}
                        target={link.href.startsWith("mailto:") ? undefined : "_blank"}
                        rel="noreferrer"
                        className="opacity-70 hover:opacity-100 transition-colors hover:text-white"
                      >
                        {link.label}
                      </a>
                    ) : (
                      <Link
                        href={link.href}
                        className="opacity-70 hover:opacity-100 transition-colors hover:text-white"
                      >
                        {link.label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>

      {/* Bottom bar */}
      <div className="pt-2 md:pt-3 border-t border-white/10 flex flex-col md:flex-row items-center justify-between gap-1.5 md:gap-3">
        <p className="text-[10px] uppercase tracking-widest opacity-50">
          Curated by @Bontha Vijay
        </p>
        <div className="flex items-center gap-4">
          <span className="text-[10px] uppercase tracking-widest opacity-50">Join the Journey:</span>
          <div className="flex items-center gap-3">
            {SOCIALS.map(({ label, href, Icon }) => (
              <a
                key={label}
                href={href}
                target={href.startsWith("mailto:") ? undefined : "_blank"}
                rel="noreferrer"
                aria-label={label}
                title={label}
                className="opacity-70 hover:opacity-100 transition-colors hover:text-white"
              >
                <Icon size={14} />
              </a>
            ))}
            <Send size={14} className="opacity-25" aria-label="Telegram bot - coming soon" />
          </div>
        </div>
      </div>
    </motion.footer>
  );
}
