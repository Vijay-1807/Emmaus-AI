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
      className="liquid-glass-dark w-full rounded-3xl p-4 md:p-7 text-white/70 mt-14 md:mt-20"
    >
      {/* Top grid — compact 3-col strip on mobile, full layout on desktop */}
      <div className="grid grid-cols-3 gap-4 md:grid-cols-12 md:gap-10 mb-5 md:mb-6">
        <div className="col-span-3 md:col-span-5">
          <div className="flex items-center gap-2 text-white">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M 4.688 136 C 68.373 136 120 187.627 120 251.312 C 120 252.883 119.967 254.445 119.905 256 L 0 256 L 0 136.096 C 1.555 136.034 3.117 136 4.688 136 Z M 251.312 136 C 252.883 136 254.445 136.034 256 136.096 L 256 256 L 136.095 256 C 136.032 254.438 136.001 252.875 136 251.312 C 136 187.627 187.627 136 251.312 136 Z M 119.905 0 C 119.967 1.555 120 3.117 120 4.688 C 120 68.373 68.373 120 4.687 120 C 3.117 120 1.555 119.967 0 119.905 L 0 0 Z M 256 119.905 C 254.445 119.967 252.883 120 251.312 120 C 187.627 120 136 68.373 136 4.687 C 136 3.117 136.033 1.555 136.095 0 L 256 0 Z" /></svg>
            <span className="font-display text-lg md:text-xl font-medium tracking-tight">Emmaus AI</span>
          </div>
          <p className="hidden md:block mt-3 text-sm leading-relaxed max-w-sm">
            Emmaus AI turns documents, datasets, images, and audio into cited
            answers — multimodal RAG with hybrid retrieval, built in the open.
          </p>
          {/* Showcase slots (phone / laptop mockups) mount here later */}
        </div>

        <div className="col-span-3 md:col-span-7 grid grid-cols-3 gap-3 md:gap-8">
          {LINK_GROUPS.map((group) => (
            <div key={group.header}>
              <h4 className="text-[11px] md:text-sm uppercase tracking-wider text-white font-medium mb-2 md:mb-3">
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
      <div className="pt-3 md:pt-4 border-t border-white/10 flex flex-col md:flex-row items-center justify-between gap-2 md:gap-4">
        <p className="text-[10px] uppercase tracking-widest opacity-50">
          Curated by @Vijay-1807
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
                <Icon size={16} />
              </a>
            ))}
            <Send size={16} className="opacity-25" aria-label="Telegram bot — coming soon" />
          </div>
        </div>
      </div>
    </motion.footer>
  );
}
